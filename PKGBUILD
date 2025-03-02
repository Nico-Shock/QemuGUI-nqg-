pkgname=nqg
pkgver=0.0.2
pkgrel=0
pkgdesc="A easy simple to use qemu gui written in python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
source=("nqg.py")
sha256sums=('c75464e460e5f9d149a02e552cb3a6d1f5ae9c55e2896aa8b0caf371a832c7d2')

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
