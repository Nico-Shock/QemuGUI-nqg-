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
sha256sums=('24905ab6600f13e7fc1fbc6601ebbef993373c24dc3c7d80836984f78f41180a')
pkgver() {
  echo "0.0.2"
}

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
