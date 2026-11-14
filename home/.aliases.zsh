# Expand aliases in the command following sudo.
alias sudo='sudo '

if _exists trash; then
  alias rm='trash'
fi

if _exists eza; then
  alias ls='eza -a --icons=auto'
  alias ll='eza -lah'
  alias tree='eza -T'
fi

if _exists bat; then
  export BAT_THEME='ansi'
  alias cat='bat -p'
fi

# WSL opens files in the Windows host without installing a Linux desktop.
if [[ "$OSTYPE" == linux* ]] && _exists explorer.exe && _exists wslpath; then
  open_command() {
    local target
    for target in "${@:-.}"; do
      if [[ "$target" == *://* ]]; then
        explorer.exe "$target"
      else
        explorer.exe "$(wslpath -w "$target")"
      fi
    done
  }
fi

if _exists open_command; then
  alias open='open_command'
fi

if [[ "$OSTYPE" == darwin* ]]; then
  alias caff='caffeinate -i'
  alias term='open -a iterm.app'
fi
alias c='clear'
alias q="cd ~ && clear"
alias e="$EDITOR"
alias -g G="| rg"
alias -g L='2>&1 | tee'
if _exists pbcopy; then
  alias -g C='| pbcopy'
fi
alias -- +x='chmod +x'
alias x+='chmod +x'
alias reload="source $HOME/.zshrc"
alias path='echo -e ${PATH//:/\\n}'

alias o='open'
alias oo='open .'

[ -d ~/Downloads ] && alias dl='cd ~/Downloads'
[ -d ~/Desktop ] && alias dt='cd ~/Desktop'
[ -d ~/dev ] && alias dev='cd ~/dev'
function mkcd {
  command mkdir -p -- "$1" && cd -- "$1"
}

alias sizes='du -sh * | sort -h'
alias get="curl -O -L"
if [[ "$OSTYPE" == linux* ]]; then
  myip() { ip -o -4 addr show scope global | awk '{print $4}' | cut -d/ -f1; }
else
  alias myip='ifconfig | sed -En "s/127.0.0.1//;s/.*inet (addr:)?(([0-9]*\.){3}[0-9]*).*/\2/p"'
fi
alias ports='lsof -i -P -n | grep LISTEN'
function killport() { lsof -tiTCP:"${1:?Usage: killport <port>}" -sTCP:LISTEN | xargs kill -9 ; }

if command -v lazygit >/dev/null 2>&1; then
  alias lg='lazygit'
fi

function gud {
  local branch main_branch remote
  branch="$(git symbolic-ref --quiet --short HEAD)" || return
  remote="$(git remote show origin)" || return
  main_branch="$(printf '%s\n' "$remote" | awk '/HEAD branch:/ {print $NF}')"

  git switch -- "$main_branch" &&
    git pull --rebase &&
    git fetch --all --tags --prune --jobs=10 || return
  if [[ "$branch" != "$main_branch" ]]; then
    git branch --delete -- "$branch"
  fi
}
