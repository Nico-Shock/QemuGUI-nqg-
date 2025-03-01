pkgname=nqg
pkgver=0.0.0
pkgrel=0
pkgdesc="A simple and easy-to-use QEMU-GUI written in Python."
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
source=("main.py")
sha256sums=('7964a8eb0dcefb794b9fcb2d50fd8aa862d1f9ae19185f4535ea70f91b0e049d')

package() {
  install -Dm755 "$srcdir/main.py" "$pkgdir/usr/bin/$pkgname"
}

