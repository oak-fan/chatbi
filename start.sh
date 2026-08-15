#!/bin/bash
SESSION="chatbi"

# 获取脚本所在目录（即 chatbi 目录）
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

tmux kill-session -t $SESSION 2>/dev/null

tmux new-session -d -s $SESSION

# 窗口0：后端主服务
tmux send-keys -t $SESSION:0 "cd $PROJECT_DIR/backend && .venv/bin/python run.py" C-m

# 窗口1：Worker
tmux new-window -t $SESSION:1
tmux send-keys -t $SESSION:1 "cd $PROJECT_DIR/backend && .venv/bin/python run_workers.py" C-m

# 窗口2：前端
tmux new-window -t $SESSION:2
tmux send-keys -t $SESSION:2 "cd $PROJECT_DIR/frontend && npm run dev" C-m

tmux attach -t $SESSION