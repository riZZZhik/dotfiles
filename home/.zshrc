# ------------------------------------------------------------------------------
# Environment
# ------------------------------------------------------------------------------

# User settings
export EDITOR=nvim

# Locale
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LANGUAGE=en_US.UTF-8

# Extend $PATH without duplicates
_extend_path() {
  [[ -d "$1" ]] || return

  # if ! $( echo "$PATH" | tr ":" "\n" | grep -qx "$1" ) ; then
  export PATH="$1:$PATH"
  # fi
}

# Add custom bin to $PATH
_extend_path "/opt/homebrew/sbin"
_extend_path "/opt/homebrew/bin"
_extend_path "$HOME/.local/bin"
_extend_path "$(brew --prefix)/opt/python@3.12/libexec/bin"

# ------------------------------------------------------------------------------
# Plugins
# ------------------------------------------------------------------------------

# Export oh-my-zsh
export ZSH="$HOME/.local/share/sheldon/repos/github.com/ohmyzsh/ohmyzsh"
plugins=(
  macos          # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/macos
  git            # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/git
  brew           # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/brew
  docker         # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/docker
  docker-compose # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/docker-compose
  sudo           # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/sudo

  colored-man-pages # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/colored-man-page

  ssh-agent
  #   gpg-agent
)

# Load sheldon plugins
eval "$(sheldon source)"

# Source if exists
_source() {
  if [[ -f $1 ]]; then
    source $1
  else
    echo "File to source not found: $1"
  fi
}

# Setup fzf
source <(fzf --zsh)

# Setup thefuck
eval $(thefuck --alias)

# Export custom aliases
_source ~/.aliases.zsh

# Enable iTerm shell integration
_source ~/.iterm2_shell_integration.zsh
