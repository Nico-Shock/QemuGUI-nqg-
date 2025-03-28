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
sha256sums=('efa7cab5bd6fa9e3c3d903147f7072ba0adca8ac00dc337c70a4a086461d2573')
pkgver() {
  echo "0.0.2"
}

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
