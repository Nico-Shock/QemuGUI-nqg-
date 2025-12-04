pkgname=nqg
pkgver=0.0.7
pkgrel=1
pkgdesc="A simple and easy-to-use QEMU GUI written in Python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
license=('GPL')
depends=('python' 'python-gobject' 'gtk3')
source=("nqg.py")
sha256sums=('c3bf06aeb8aee7e5073128c8d4fcfccdcf834dad569431a6d51e53b68d9cc0d9')

package() {
    install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/nqgpkg"
}
