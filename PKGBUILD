pkgname=nqg
pkgver=0.0.2
pkgrel=0
pkgdesc="A easy simple to use qemu gui written in python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
source=("nqg.py")
sha256sums=('0efa83caf5e65153b666cd37dedfb350395ce9186c6fbb83b616ec0a7d0bbacf')

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
