# !/usr/bin/env bash

set -e
trap on_error SIGTERM

GITHUB_REPO_URL_BASE="https://github.com/rizzzhik/dotfiles"

# Initialize helpers

e='\033'
RESET="${e}[0m"
BOLD="${e}[1m"
CYAN="${e}[0;96m"
RED="${e}[0;91m"
YELLOW="${e}[0;93m"
GREEN="${e}[0;92m"

_exists() {
  command -v "$1" > /dev/null 2>&1
}

info() {
  echo -e "${CYAN}${*}${RESET}"
}

error() {
  echo -e "${RED}${*}${RESET}"
}

success() {
  echo -e "${GREEN}${*}${RESET}"
}

finish() {
  success "Done!"
  sleep 1
}

on_error() {
  echo
  error "Wow... Something serious happened!"
  error "Though, I don't know what really happened :("
  error "In case, you want to help me fix this problem, raise an issue -> ${CYAN}${GITHUB_REPO_URL_BASE}issues/new${RESET}"
  echo
  exit 1
}

# Initialize functions

update_linux() {
  if [ "$(uname)" != "Linux" ]; then
    return
  fi

  info "Updating packet managers..."
  sudo apt update && sudo apt upgrade

  finish
}

install_homebrew() {
  info "Trying to detect installed Homebrew..."

  if ! _exists brew; then
    info "Installing Homebrew..."
    bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    success "You already have Homebrew installed. Skipping..."
  fi

  finish
}

install_software() {
  if [ "$(uname)" != "Darwin" ]; then
    return
  fi

  info "Installing software..."

  # Homebrew Bundle
  if _exists brew; then
    brew bundle
  else
    error "Error: Brew is not available"
  fi

  # fzf
  echo "y\ny\nn" | $(brew --prefix)/opt/fzf/install

  # Colorls
  sudo gem install colorls

  finish
}

install_python() {
  if ! _exists python3.11; then
    info "Installing Python..."

    if [ "$(uname)" = "Darwin" ]; then
      brew install python@3.11
      brew link --overwirte python@3.11
    elif [ "$(uname)" = "Linux" ]; then
      sudo apt install wget build-essential libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev libffi-dev zlib1g-dev
      sudo add-apt-repository ppa:deadsnakes/ppa
      sudo apt install python3.11
    else
      error "Error: Failed to install python3.11!"
      exit 1
    fi
  else
    success "You already have Python installed. Skipping..."
  fi

  packages=(
    pip
    poetry
  )
  echo "Installing: ${packages[*]}"
  python3.11 -m pip install --upgrade "${packages[@]}"

  finish
}

on_finish() {
  echo
  success "Setup was successfully done!"
  success "Happy Coding!"
  echo
  echo -ne "$RED"'-_-_-_-_-_-_-_-_-_-_-_-_-_-_'
  echo -e  "$RESET""$BOLD"',------,'"$RESET"
  echo -ne "$YELLOW"'-_-_-_-_-_-_-_-_-_-_-_-_-_-_'
  echo -e  "$RESET""$BOLD"'|   /\_/\\'"$RESET"
  echo -ne "$GREEN"'-_-_-_-_-_-_-_-_-_-_-_-_-_-'
  echo -e  "$RESET""$BOLD"'~|__( ^ .^)'"$RESET"
  echo -ne "$CYAN"'-_-_-_-_-_-_-_-_-_-_-_-_-_-_'
  echo -e  "$RESET""$BOLD"'""  ""'"$RESET"
  echo
  info "P.S: Don't forget to restart a terminal :)"
  echo
}
