_exists() {
  if command -v -- "$1" >/dev/null 2>&1; then
    return 0
  else
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

_extend_path() {
  [[ -d "$1" ]] || return
  export PATH="$1:$PATH"
}

export EDITOR="${EDITOR:-vi}"
if command -v nvim >/dev/null 2>&1; then
  export EDITOR=nvim
fi
typeset -U path PATH

export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export LANGUAGE=en_US.UTF-8

if [ "$(uname)" = "Darwin" ]; then
  _extend_path "/opt/homebrew/sbin"
  _extend_path "/opt/homebrew/bin"
  _extend_path "$HOME/go/bin"
fi
_extend_path "$HOME/.local/bin"

HISTSIZE=100000
SAVEHIST=50000
HISTFILE="$HOME/.zsh_history"
setopt HIST_IGNORE_DUPS
setopt HIST_SAVE_NO_DUPS
setopt HIST_IGNORE_SPACE
setopt SHARE_HISTORY

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
)

# The ssh-agent plugin reads these settings while loading.
if [[ "$OSTYPE" == "darwin"* ]]; then
  zstyle :omz:plugins:ssh-agent ssh-add-args --apple-use-keychain
fi

# Private plugin settings must load before plugin initialization.
if [[ -f "$HOME/.zshrc.private.early.zsh" ]]; then
  source "$HOME/.zshrc.private.early.zsh"
fi

if _exists sheldon; then
  eval "$(sheldon source)"
fi

autoload -Uz edit-command-line
zle -N edit-command-line
zstyle :zle:edit-command-line editor "$EDITOR"
bindkey -M emacs '^Xe' edit-command-line
bindkey -M viins '^Xe' edit-command-line
bindkey -M emacs '^Xq' push-line
bindkey -M viins '^Xq' push-line

if _exists fzf; then
  _source ~/.config/fzf.zsh
  source <(fzf --zsh)
  bindkey '\er' fzf-history-widget
fi

if _exists zoxide; then
  eval "$(zoxide init zsh)"
  function _cd_zoxide {
    if (( $# )); then
      z "$@"
    else
      zi
    fi
  }
  alias cd='_cd_zoxide'
  compdef _cd _cd_zoxide
fi

if [[ -f ~/.iterm2_shell_integration.zsh ]]; then
  source ~/.iterm2_shell_integration.zsh
fi

# Load personal command overrides after plugins and integrations.
_source ~/.aliases.zsh

if [ -f ~/.zshrc.private.zsh ]; then
  source ~/.zshrc.private.zsh
fi

if _exists direnv; then
  eval "$(direnv hook zsh)"
fi

if _exists starship; then
  eval "$(starship init zsh)"
fi

if command -v atuin >/dev/null 2>&1; then
  export ATUIN_CONFIG_DIR="$HOME/.config/atuin"
  eval "$(atuin init zsh --disable-up-arrow --disable-ai)"
fi

fpath+=~/.zfunc; autoload -Uz compinit; compinit
