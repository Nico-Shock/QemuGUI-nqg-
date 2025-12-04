pkgname=nqg
pkgver=0.0.6
pkgrel=1
pkgdesc="A simple and easy-to-use QEMU GUI written in Python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
makedepends=('python')
optdepends=('qemu')
source=("nqg.py")
sha256sums=('1e7ffca714ca2d21dbafea44eedc1051c7d96d071f416aefb6c68f35fd3ab33f')
pkgver() {
  echo "0.0.7"
}

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
