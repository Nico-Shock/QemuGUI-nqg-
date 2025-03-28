pkgname=nqg
pkgver=0.0.3
pkgrel=0
pkgdesc="A simple and easy-to-use QEMU GUI written in Python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
makedepends=('python')
optdepends=('qemu')
source=("nqg.py")
sha256sums=('328be5b023efa885b68e6a6dd36aa3724d89885225a7150d187e0fba54aa7f94')
pkgver() {
  echo "0.0.2"
}

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
