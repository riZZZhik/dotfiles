# Aliases

# Enable aliases to be sudo’ed
#   http://askubuntu.com/questions/22037/aliases-not-available-when-using-sudo
alias sudo='sudo '

# Just cuz c shorter than clear
alias c='clear'

# Go to the /home/$USER (~) directory and clears window of your terminal
alias q="cd ~ && clear"

# Commands Shortcuts
alias e="$EDITOR"
alias -g G="| rg"
alias -- +x='chmod +x'
alias x+='chmod +x'

# Open aliases
alias open='open_command'
alias o='open'
alias oo='open .'
alias term='open -a iterm.app'

# Quick reload of zsh environment
alias reload="source $HOME/.zshrc"

# Show $PATH in readable view
alias path='echo -e ${PATH//:/\\n}'

# Some other useful shortcuts
alias myip='ifconfig | sed -En "s/127.0.0.1//;s/.*inet (addr:)?(([0-9]*\.){3}[0-9]*).*/\2/p"'
alias ports='lsof -i -P -n | grep LISTEN'
alias get="curl -O -L"
alias sizes='du -sh * | sort -h'

# Git Shortcuts
function gud {
  branch=$(git branch --show-current)
  main_branch=$(git remote show origin | grep 'HEAD branch' | awk '{print $NF}')

  git switch $main_branch
  git pull --rebase
  git fetch --all --tags --prune --jobs=10
  git branch --delete --force $branch
}

# Folders Shortcuts
[ -d ~/Downloads ] && alias dl='cd ~/Downloads'
[ -d ~/Desktop ] && alias dt='cd ~/Desktop'
[ -d ~/dev ] && alias dev='cd ~/dev'
function mkcd {
  command mkdir -p $1 && cd $1
}
