# Batch Video Transcoder

**Batch Video Transcoder** is a CLI tool for GPU accelerated transcoding of large amount of Video files to reduce the size, while ensure preserving the best video quality. It uses [FFmpeg](https://ffmpeg.org) transcode the Video files and [VMAF](https://github.com/Netflix/vmaf) to analize the output quality, if the desired quality treshold has not been meet, the Video will be transcoded again. 

## How to run

### Example commands (Windows PowerShell): 

Transcode a single file and keep the result in the `out` directory:

```pwsh
python batch-video-transcoder.py -i .\test-file.mp4 -o .\out
```

Transcode multiple files from `in` directory and keep the results in the `out` directory: 

```pwsh
python batch-video-transcoder.py -i .\in\* -t 14 --vmaf-workers 2 -cq 38 -q 95 -o .\out
```

Get help: 

```pwsh
python batch-video-transcoder.py --help
```

## General usage

Help command: 

```
usage: batch-video-transcoder.py [-h] [-i INPUT [INPUT ...]] [-o OUTPUT] [-cq [0 - 50]] [-q [0 - 100]] [-v] [-t THREADS] [--transcode-workers TRANSCODE_WORKERS] [--vmaf-workers VMAF_WORKERS]

options:
  -h, --help            show this help message and exit
  -i INPUT [INPUT ...], --input INPUT [INPUT ...]
                        input file path (default: None)
  -o OUTPUT, --output OUTPUT
                        output directory path (default: ./out)
  -cq [0 - 50], --init-cq [0 - 50]
                        initial constant quality (cq) value to transcode with, decreases by 2 on every step (default: 40)
  -q [0 - 100], --quality-treshold [0 - 100]
                        the quality level, below which the file will be transcoded again with higher cq (default: 95)
  -v, --verbose
  -t THREADS, --threads THREADS
                        number of threads to video transcodecompute on (default: 14)
  --transcode-workers TRANSCODE_WORKERS
                        number of paralel workers to transcode on (default: 1)
  --vmaf-workers VMAF_WORKERS
                        number of paralel workers to compute vmaf on (default: 1)
```

## Installation

You don't need to install, just download or clone the repo. If the requirements below are met you should be able to run the `batch-video-transcoder.py` directly. 

###  Requirements

- Python >= 3.10 (I think, developed and tested on 3.12)
- Nvidia GPU with `hevc_nvenc`
- `ffmpeg` compiled with `vmaf` in `PATH` environmental variable

Tested on Windows 11, but I don't see a reason why it shouldn't work on Linux

### FFmpeg

I used `gyan.dev` Windows build avaiable through `winget`, which is recommended on [FFmpeg download page](https://ffmpeg.org/download.html#build-windows) and is compiled with VMAF. 

```pwsh
winget install Gyan.FFmpeg
```

## License 

GNU General Public License v3.0 or later

See [LICENSE](./LICENSE) to see full text
