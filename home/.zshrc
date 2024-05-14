# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# ------------------------------------------------------------------------------
# Environment
# ------------------------------------------------------------------------------

# User settings
export EDITOR="nvim"

# Locale
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LANGUAGE=en_US.UTF-8

# Python
export POETRY_VIRTUALENVS_IN_PROJECT=true

# Extend $PATH without duplicates
_extend_path() {
  [[ -d "$1" ]] || return

  # if ! $( echo "$PATH" | tr ":" "\n" | grep -qx "$1" ) ; then
    export PATH="$1:$PATH"
  # fi
}

# Add custom bin to $PATH
_extend_path "/opt/homebrew/bin"
_extend_path "$HOME/.local/bin"
_extend_path "$(brew --prefix)/opt/python@3.11/libexec/bin"

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

  colored-man-pages       # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/colored-man-page

  ssh-agent
  gpg-agent
)

# Load sheldon plugins
eval "$(sheldon source)"

# Source if exists
_source() {
  if [[ -f $1 ]] ; then
    source $1
  else
    echo "File to source not found: $1"
  fi
}

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
_source ~/.p10k.zsh

# Fix p10k bugs
unset ZSH_AUTOSUGGEST_USE_ASYNC

# Setup fzf
_source ~/.fzf.zsh

# Setup thefuck
eval $(thefuck --alias)

# Color ls (https://github.com/athityakumar/colorls)
_source $(dirname $(gem which colorls))/tab_complete.sh

# Export custom aliases
_source ~/.aliases.zsh

# Export secrets
_source ~/.secrets.sh

# ------------------------------------------------------------------------------

# Enable iTerm shell integration
_source ~/.iterm2_shell_integration.zsh
