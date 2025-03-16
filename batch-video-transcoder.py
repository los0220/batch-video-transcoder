#!/usr/bin/env python3

#   Batch Video Transcoder
#   Copyright (C) 2025,  Maciej Jasiński <maciejj2000@gmail.com>
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <https://www.gnu.org/licenses/>.


__version__ = "1.0.0"


from os import path
import asyncio
import re

import argparse
from glob import glob


DEFAULT_QUALITY_TRESHOLD = 95
DEFAULT_TRANSCODE_WORKERS = 1
DEFAULT_VMAF_WORKERS = 1
DEFAULT_VMAF_THREADS = 14
DEFAULT_CQ_STEP = 2
DEFAULT_CQ_INITIAL = 40
DEFAULT_OUT_DIR = "./out"
DEFAULT_OUT_FILE_EXTENSION = ".mkv"


class CustomAsyncQueue(asyncio.Queue):
    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        self._unfinished_tasks_custom = 0

    def put_nowait(self, item) -> None:
        super().put_nowait(item)
        self._unfinished_tasks_custom += 1

    def task_done(self) -> None:
        super().task_done()
        self._unfinished_tasks_custom -= 1

    def get_unfinished_tasks(self) -> int:
        return self._unfinished_tasks_custom


def ffmpeg_compile_cmd(
    input_path: str | list[str],
    output_path: str,
    ffmpeg_args: dict,
    override_output: bool = False,
    progress: bool = False,
    nostdin: bool = True,
    nostats: bool = True,
) -> list[str]:

    cmd = ["ffmpeg"]

    if isinstance(input_path, str):
        input_path = [input_path]
    if override_output:
        cmd.append("-y")
    if progress:
        cmd.extend(["-progress", "-"])
    if nostdin:
        cmd.append("-nostdin")
    if nostats:
        cmd.append("-nostats")

    for _input in input_path:
        cmd.extend(["-i", path.abspath(_input)])

    for flag, arg in ffmpeg_args.items():
        cmd.extend(["-" + str(flag), str(arg)])

    if output_path == "-":
        cmd.append(output_path)
    else:
        cmd.append(path.abspath(output_path))

    return cmd


async def ffmpeg_run_async(
    ffmpeg_cmd: list[str], verbose: bool = False
) -> tuple[str, str]:

    if verbose:
        print(*ffmpeg_cmd)

    try:
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        stdout, stderr = await process.communicate()

    finally:
        if process.returncode is None:
            process.terminate()

    return stdout, stderr


async def transcode_async(
    in_path: str, out_path: str, cq: int, verbose: bool = False
) -> None:

    transcode_settings = {
        "vcodec": "hevc_nvenc",
        "preset": "slow",
        "rc": "vbr",
        "cq": cq,
        "ac": 1,  # squish audio channels to mono
        "map_metadata": 0,  # preserve metadata
    }

    ffmpeg_cmd = ffmpeg_compile_cmd(
        in_path, out_path, transcode_settings, override_output=True
    )
    await ffmpeg_run_async(ffmpeg_cmd, verbose=verbose)


async def transcode_worker(
    transcode_q: CustomAsyncQueue,
    vmaf_q: CustomAsyncQueue,
    verbose: bool = False,
) -> None:

    while True:
        in_path, out_path, cq = await transcode_q.get()

        print(f"transcode start! {cq} {in_path}")

        await transcode_async(in_path, out_path, cq, verbose=verbose)

        await vmaf_q.put((out_path, in_path, cq))
        transcode_q.task_done()

        print(f"transcode done! {cq} {in_path}")


def vmaf_get_score(stdout: bytes) -> float | None:
    match = re.search(r"(?<=VMAF score: )\d+\.\d+", stdout.decode())

    if match:
        return float(match.group())
    else:
        return None


async def vmaf_async(
    distorted_path: str, reference_path: str, threads: int, verbose: bool = False
) -> float | None:

    vmaf_settings = {
        "filter_complex": f"libvmaf=n_threads={threads}",
        "f": "null",
    }

    ffmpeg_cmd = ffmpeg_compile_cmd(
        [distorted_path, reference_path], "-", vmaf_settings
    )

    stdout, _ = await ffmpeg_run_async(ffmpeg_cmd, verbose=verbose)
    vmaf_score = vmaf_get_score(stdout)

    return vmaf_score


async def vmaf_worker(
    transcode_q: CustomAsyncQueue,
    vmaf_q: CustomAsyncQueue,
    threshold: float,
    threads: int,
    verbose: bool = False,
    cq_step: int = DEFAULT_CQ_STEP,
) -> None:

    while True:
        distorted, reference, cq = await vmaf_q.get()

        print(f"vmaf start! {cq} {reference}")

        vmaf_score = await vmaf_async(distorted, reference, threads, verbose=verbose)

        if vmaf_score is not None:
            new_cq = cq - cq_step

            if vmaf_score < threshold and new_cq >= 0:
                await transcode_q.put((reference, distorted, new_cq))

            print(f"vmaf done! {cq} {reference}  Score: {vmaf_score:.2f}")
        else:
            await vmaf_q.put((distorted, reference, cq))

            print(f"vmaf failed! {cq} {reference} retrying!")

        vmaf_q.task_done()


def workers_create(
    transcode_q: CustomAsyncQueue,
    vmaf_q: CustomAsyncQueue,
    n_transcode_workers: int,
    n_vmaf_workser: int,
    threshold: float,
    threads: int,
    verbose: bool = False,
) -> list[asyncio.Task]:

    worker_tasks = []

    for _ in range(n_transcode_workers):
        worker_tasks.append(
            asyncio.create_task(transcode_worker(transcode_q, vmaf_q, verbose=verbose))
        )
    for _ in range(n_vmaf_workser):
        worker_tasks.append(
            asyncio.create_task(
                vmaf_worker(transcode_q, vmaf_q, threshold, threads, verbose=verbose)
            )
        )

    return worker_tasks


def deduplicate_files(files: list[str]) -> list[str]:
    return list(dict.fromkeys(files))


def queues_populate(
    transcode_q: CustomAsyncQueue,
    vmaf_q: CustomAsyncQueue,
    input_files: list[str],
    output_dir: str,
    init_cq: int,
    out_file_extension: str = DEFAULT_OUT_FILE_EXTENSION,
) -> None:

    input_files = deduplicate_files(input_files)

    for input_file in input_files:
        out_name = path.basename(path.splitext(input_file)[0] + out_file_extension)
        out_path = path.normpath(path.join(output_dir, out_name))
        transcode_q.put_nowait((input_file, out_path, init_cq))


async def queues_wait_for_done(
    transcode_q: CustomAsyncQueue,
    vmaf_q: CustomAsyncQueue,
    worker_tasks: list[asyncio.Task],
) -> None:

    while transcode_q.get_unfinished_tasks() > 0 or vmaf_q.get_unfinished_tasks() > 0:
        await transcode_q.join()
        await vmaf_q.join()

    for task in worker_tasks:
        task.cancel()


async def main() -> None:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-i", "--input", type=str, nargs="+", help="input file path")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=DEFAULT_OUT_DIR,
        help="output directory path",
    )
    parser.add_argument(
        "-cq",
        "--init-cq",
        type=int,
        default=DEFAULT_CQ_INITIAL,
        choices=range(0, 51),
        metavar="[0 - 50]",
        help="initial constant quality (cq) value to transcode with, "
        + f"decreases by {DEFAULT_CQ_STEP} on every step",
    )
    parser.add_argument(
        "-q",
        "--quality-treshold",
        type=int,
        default=DEFAULT_QUALITY_TRESHOLD,
        choices=range(0, 101),
        metavar="[0 - 100]",
        help="the quality level, below which the file will be transcoded again with higher cq",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=DEFAULT_VMAF_THREADS,
        help="number of threads to compute on",
    )
    parser.add_argument(
        "--transcode-workers",
        type=int,
        default=DEFAULT_TRANSCODE_WORKERS,
        help="number of paralel workers to transcode on",
    )
    parser.add_argument(
        "--vmaf-workers",
        type=int,
        default=DEFAULT_VMAF_WORKERS,
        help="number of paralel workers to compute vmaf on",
    )
    args = parser.parse_args()

    input_files = []
    for input_str in args.input:
        input_files.extend(glob(input_str))

    transcode_q = CustomAsyncQueue()
    vmaf_q = CustomAsyncQueue()

    queues_populate(transcode_q, vmaf_q, input_files, args.output, args.init_cq)

    worker_tasks = workers_create(
        transcode_q,
        vmaf_q,
        args.transcode_workers,
        args.vmaf_workers,
        args.quality_treshold,
        args.threads,
        args.verbose,
    )

    await queues_wait_for_done(transcode_q, vmaf_q, worker_tasks)


if __name__ == "__main__":
    asyncio.run(main())
