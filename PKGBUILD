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
sha256sums=('f9c2b4f6f4e821ec1ea3c23b0eb0277737df420841a63ed26e3ae967abc717ab')
pkgver() {
  echo "0.0.6"
}

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
