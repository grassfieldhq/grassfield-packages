# Shared by scripts/app-check.sh and scripts/app-repack.sh (sourced, not run): what a bundled app's package may hold.
#
#   app_names NAME            sets $bin (the app's binary) and $meta (its metainfo file, or empty); returns 1 for a name that is
#                             not a bundled app
#   app_path_ok NAME PATH     0 if PATH (as bsdtar lists it: a folder ends in /) is one of the app's own paths
#
# The paths are EXACTLY the app's own: .PKGINFO, .BUILDINFO, .MTREE; usr/bin/<its binary> alone; usr/share/applications/<its
# .desktop> alone; its hicolor icons (<binary>.png or .svg under hicolor/<size>/apps/); its metainfo file if it has one; and
# usr/share/licenses/<pkgname>/ with what is below. No .INSTALL (no scriptlet), no other binary, no hook, no usr/share/doc.

app_names() {
  case $1 in
    grassfield-sanaga) bin=sanaga meta=site.grassfield.Sanaga.metainfo.xml ;;
    grassfield-notes) bin=grassfield-notes meta="" ;;
    *) return 1 ;;
  esac
}

app_path_ok() {
  local name=$1 p=$2 bin meta icon
  app_names "$name" || return 1
  [[ $p != *..* && $p != /* ]] || return 1
  case $p in
    .PKGINFO | .BUILDINFO | .MTREE | usr/ | usr/bin/ | usr/share/ | usr/share/applications/ | usr/share/icons/ | usr/share/icons/hicolor/ | usr/share/licenses/ | usr/share/metainfo/ | "usr/bin/$bin" | "usr/share/applications/$bin.desktop" | "usr/share/licenses/$name/" | "usr/share/licenses/$name/"*) return 0 ;;
  esac
  icon="^usr/share/icons/hicolor/(scalable|[0-9]+x[0-9]+(@2)?)/(apps/($bin\.(png|svg))?)?$"
  [[ $p =~ $icon ]] && return 0
  [[ -n $meta && $p == "usr/share/metainfo/$meta" ]] && return 0
  return 1
}
