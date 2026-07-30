#!/bin/sh
set -eu

INSTALL_DIR=${1:?Použití: install_ci_security_tools.sh INSTALL_DIR}
mkdir -p "$INSTALL_DIR"
WORK_DIR=$(mktemp -d)
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT INT TERM

install_tool() {
  name=$1
  version=$2
  archive=$3
  checksum=$4
  repository=$5
  url="https://github.com/$repository/releases/download/v$version/$archive"
  curl --fail --silent --show-error --location "$url" --output "$WORK_DIR/$archive"
  printf '%s  %s\n' "$checksum" "$WORK_DIR/$archive" | sha256sum --check -
  tar -xzf "$WORK_DIR/$archive" -C "$WORK_DIR" "$name"
  install -m 0755 "$WORK_DIR/$name" "$INSTALL_DIR/$name"
}

install_tool \
  syft 1.46.0 syft_1.46.0_linux_amd64.tar.gz \
  d654f678b709eb53c393d38519d5ed7d2e57205529404018614cfefa0fb2b5ca \
  anchore/syft
install_tool \
  grype 0.116.1 grype_0.116.1_linux_amd64.tar.gz \
  0122df7b655981abe547ad3d2190d65551dac6a2bfc80b4dc2a989b5d0587458 \
  anchore/grype
install_tool \
  gitleaks 8.30.1 gitleaks_8.30.1_linux_x64.tar.gz \
  551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb \
  gitleaks/gitleaks

"$INSTALL_DIR/syft" version
"$INSTALL_DIR/grype" version
"$INSTALL_DIR/gitleaks" version
