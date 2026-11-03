#!/bin/zsh
# Restart the web UI on the VM. The DeepSeek key is read from your login shell
# and piped over SSH into the program's memory; it is never written on the VM.
VM=${VM:?set VM=ubuntu@<vm-ip>}
KEY=${KEY:-~/.ssh/aws-guided.pem}
PORT=${1:-8000}   # 8000 = Firefox desktop container, 8001 = headless Chromium, 8002 = full Chromium

zsh -ic 'printf "%s\n" "$DEEPSEEK_API_KEY"' 2>/dev/null | ssh -i $KEY $VM '
  fuser -k 8770/tcp 2>/dev/null; sleep 1
  read -r K
  [ -z "$K" ] && { echo "no key received"; exit 1; }
  cd ~/guided_agent
  DEEPSEEK_API_KEY=$K DESKTOP_URL=http://127.0.0.1:'"$PORT"' \
    nohup .venv/bin/python webdemo.py > webdemo.log 2>&1 < /dev/null &
  sleep 4
  ss -ltn | grep -q 8770 && echo "web UI is up on the VM" || cat webdemo.log
'
