#!/bin/sh
# Reproducible synthetic input, not a recording of a real meeting.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
model_dir=${1:-"$project_dir/.local/whisper-tiny"}
mkdir -p "$project_dir/.local/validation"
sample_dir=$(mktemp -d "$project_dir/.local/validation/audio-synthetic-XXXXXX")
say -v Tingting -r 155 -o "$sample_dir/chinese.aiff" \
  '今天讨论课程实验报告。数据清洗已经完成。小王明天下午提交实验报告。参考文献还需要整理。是否增加对照实验，下次再讨论。'
"$project_dir/.venv/bin/mcpm" audio "$sample_dir/chinese.aiff" \
  --whisper-model "$model_dir" --language zh --output-dir "$sample_dir/results"
