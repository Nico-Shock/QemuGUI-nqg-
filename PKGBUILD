pkgname=nqg
pkgver=0.0.2
pkgrel=0
pkgdesc="A easy simple to use qemu gui written in python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
source=("nqg.py")
sha256sums=('51f9c621a699d620307dcc8174eaebcc47374d82fe1571200fc09acdcec6099c')

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
