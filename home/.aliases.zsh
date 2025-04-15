# Aliases

# Enable aliases to be sudo’ed
#   http://askubuntu.com/questions/22037/aliases-not-available-when-using-sudo
alias sudo='sudo '

# Just bcoz c shorter than clear
alias c='clear'

# Go to the /home/$USER (~) directory and clears window of your terminal
alias q="cd ~ && clear"

# Commands Shortcuts
alias e="$EDITOR"
alias -g G="| grep"
alias -- +x='chmod +x'
alias x+='chmod +x'

# Open aliases
alias open='open_command'
alias o='open'
alias oo='open .'
alias term='open -a iterm.app'

# Quick reload of zsh environment
alias reload="source $HOME/.zshrc"

# Quick jump to dotfiles
alias dotfiles="code $DOTFILES"

# My IP
alias myip='ifconfig | sed -En "s/127.0.0.1//;s/.*inet (addr:)?(([0-9]*\.){3}[0-9]*).*/\2/p"'

# Show $PATH in readable view
alias path='echo -e ${PATH//:/\\n}'

# Download file with original filename
alias get="curl -O -L"

# Git Shortcuts
function gud {
  branch=$(git branch --show-current)
  git switch develop
  git pull --rebase
  git fetch --all --tags --prune --jobs=10
  git branch --delete --force $branch
}

# Folders Shortcuts
[ -d ~/Downloads ] && alias dl='cd ~/Downloads'
[ -d ~/Desktop ] && alias dt='cd ~/Desktop'
[ -d ~/dev ] && alias dev='cd ~/dev'
function mkcd {
  command mkdir $1 && cd $1
}

# Check if a command exists
_exists() {
  command -v $1 >/dev/null 2>&1
}

# Avoid stupidity with trash-cli:
# https://github.com/sindresorhus/trash-cli
# or use default rm -i
if _exists trash; then
  alias rm='trash'
fi

# Use tldr as help util
if _exists tldr; then
  alias help="tldr"
fi

# Better ls - https://github.com/eza-community/eza
if _exists eza; then
  alias ls='eza -a --icons=auto'
  alias ll='eza -lah'
  alias tree='eza -T'
fi

# Cat with syntax highlighting - https://github.com/sharkdp/bat
if _exists bat; then
  # Run to list all themes:
  #   bat --list-themes
  export BAT_THEME='ansi'
  alias cat='bat -p'
fi
