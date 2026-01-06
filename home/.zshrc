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

  if ! $( echo "$PATH" | tr ":" "\n" | grep -qx "$1" ) ; then
    export PATH="$1:$PATH"
  fi
}

# Add custom bin to $PATH
_extend_path "$HOME/.local/bin"
if [ "$(uname)" = "Darwin" ]; then
  _extend_path "/opt/homebrew/sbin"
  _extend_path "/opt/homebrew/bin"
  _extend_path "$(brew --prefix)/opt/python@3.12/libexec/bin"
fi

# ------------------------------------------------------------------------------
# Plugins
# ------------------------------------------------------------------------------

# Completions
autoload -Uz compinit
zmodload -i zsh/complist
compinit -C

# Export oh-my-zsh
export ZSH="$HOME/.local/share/sheldon/repos/github.com/ohmyzsh/ohmyzsh"
plugins=(
  macos          # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/macos
  git            # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/git
  brew           # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/brew
  docker         # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/docker
  docker-compose # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/docker-compose
  sudo           # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/sudo

  colored-man-pages # https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/colored-man-pages

  ssh-agent
  #   gpg-agent
)

# Load sheldon plugins
eval "$(sheldon source)"

# Check if a command/file exists
_exists() {
  if command -v -- "$1" >/dev/null 2>&1; then
    return 0
  else
    echo "Command not found: $1" >&2
    return 1
  fi
}

_source() {
  if [[ -f $1 ]]; then
    source $1
  else
    echo "File not found: $1"
  fi
}

# Trash CLI - https://github.com/sindresorhus/trash-cli
if _exists trash; then
  alias rm='trash'
fi

# Use tldr as help util - https://github.com/tldr-pages/tldr
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

# Fuzzy finder - https://github.com/junegunn/fzf
if _exists fzf; then
  source <(fzf --zsh)
fi

# Use passphrase from macOS keychain
if [[ "$OSTYPE" == "darwin"* ]]; then
  zstyle :omz:plugins:ssh-agent ssh-add-args --apple-load-keychain
fi

# Export custom aliases
_source ~/.aliases.zsh

# Modern cd - https://github.com/ajeetdsouza/zoxide
if _exists zoxide; then
  eval "$(zoxide init zsh)"
fi

# Enable iTerm shell integration
if [ "$(uname)" = "Darwin" ]; then
  _source ~/.iterm2_shell_integration.zsh
fi
