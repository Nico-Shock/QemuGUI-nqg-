pkgname=nqg
pkgver=0.0.2
pkgrel=0
pkgdesc="A simple and easy-to-use QEMU GUI written in Python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
makedepends=('python')
optdepends=('qemu')
source=("nqg.py")
sha256sums=('6a24052067b1db220909391bc6a0361b4acbbde3d53e0e0f58186dc77abdb101')
pkgver() {
  echo "0.0.2"
}

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
