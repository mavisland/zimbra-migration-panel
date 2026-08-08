#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Bu betiği sudo ile çalıştırın: sudo bash scripts/install-imapsync-ubuntu.sh" >&2
  exit 1
fi

apt-get update
apt-get install -y \
  wget make time cpanminus \
  libauthen-ntlm-perl libclass-load-perl libcrypt-openssl-rsa-perl \
  libcrypt-ssleay-perl libdata-uniqid-perl libdigest-hmac-perl \
  libdist-checkconflicts-perl libencode-imaputf7-perl libfile-copy-recursive-perl \
  libfile-tail-perl libio-compress-perl libio-socket-inet6-perl \
  libio-socket-ssl-perl libio-tee-perl libjson-webtoken-perl \
  libmail-imapclient-perl libmodule-scandeps-perl libnet-dbus-perl \
  libnet-dns-perl libnet-ssleay-perl libpar-packer-perl \
  libproc-processtable-perl libreadonly-perl libregexp-common-perl \
  libsys-meminfo-perl libterm-readkey-perl libtest-fatal-perl \
  libtest-mock-guard-perl libtest-mockobject-perl libtest-pod-perl \
  libtest-requires-perl libtest-simple-perl libunicode-string-perl \
  liburi-perl libtest-nowarnings-perl libtest-deep-perl libtest-warn-perl

tmp_file=$(mktemp)
trap 'rm -f "$tmp_file"' EXIT
wget -O "$tmp_file" https://raw.githubusercontent.com/imapsync/imapsync/master/imapsync
install -m 0755 "$tmp_file" /usr/local/bin/imapsync

/usr/local/bin/imapsync --version
echo "imapsync kurulumu tamamlandı: /usr/local/bin/imapsync"
