pkgname=nqg
pkgver=0.0.5
pkgrel=1
pkgdesc="A simple and easy-to-use QEMU GUI written in Python"
arch=('x86_64')
url="https://github.com/Nico-Shock/QemuGUI-nqg-"
depends=('python')
makedepends=('python')
optdepends=('qemu')
source=("nqg.py")
sha256sums=('568b8f857b64e009969f986e5d9bbe80c1126edeeaba61a1e12c4b8b0274c10f')
pkgver() {
  echo "0.0.5"
}

package() {
  install -Dm755 "$srcdir/nqg.py" "$pkgdir/usr/bin/$pkgname"
}
