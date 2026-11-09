# Shared by scripts/app-check.sh and scripts/app-repack.sh (sourced, not run): what a bundled app's package may hold.
#
#   app_names NAME            sets $bin (the app's binary) and $meta (its metainfo file, or empty); returns 1 for a name that is
#                             not a bundled app
#   app_path_ok NAME PATH     0 if PATH (as bsdtar lists it: a folder ends in /) is one of the app's own paths
#
# The paths are EXACTLY the app's own: .PKGINFO, .BUILDINFO, .MTREE; usr/bin/<its binary> alone; usr/share/applications/<its
# .desktop> alone; its hicolor icons (<binary>.png or .svg under hicolor/<size>/apps/); its metainfo file if it has one; and
# usr/share/licenses/<pkgname>/ with what is below. No .INSTALL (no scriptlet), no other binary, no hook, no usr/share/doc.
# And every segment of every path, the licence files included, is made only of [A-Za-z0-9._@+-]: no space, control byte,
# newline or invalid UTF-8 (libalpm writes a file name raw, one per line, into the local database: a name with a newline
# would read back as another entry), and no segment starts with a dot except .PKGINFO, .BUILDINFO and .MTREE at the top.

app_names() {
  case $1 in
    grassfield-sanaga) bin=sanaga meta=site.grassfield.Sanaga.metainfo.xml ;;
    grassfield-notes) bin=grassfield-notes meta="" ;;
    *) return 1 ;;
  esac
}

app_path_ok() {
  local LC_ALL=C name=$1 p=$2 bin meta icon seg rest
  app_names "$name" || return 1
  [[ -n $p && $p != /* && $p != *//* ]] || return 1
  # Plain segments only (bytes, not a locale's idea of letters).
  rest=${p%/}
  while :; do
    seg=${rest%%/*}
    [[ $seg =~ ^[A-Za-z0-9._@+-]+$ ]] || return 1
    if [[ $seg == .* ]]; then
      [[ $rest == "$seg" && ( $seg == .PKGINFO || $seg == .BUILDINFO || $seg == .MTREE ) ]] || return 1
    fi
    [[ $rest == */* ]] || break
    rest=${rest#*/}
  done
  case $p in
    .PKGINFO | .BUILDINFO | .MTREE | usr/ | usr/bin/ | usr/share/ | usr/share/applications/ | usr/share/icons/ | usr/share/icons/hicolor/ | usr/share/licenses/ | usr/share/metainfo/ | "usr/bin/$bin" | "usr/share/applications/$bin.desktop" | "usr/share/licenses/$name/" | "usr/share/licenses/$name/"*) return 0 ;;
  esac
  icon="^usr/share/icons/hicolor/(scalable|[0-9]+x[0-9]+(@2)?)/(apps/($bin\.(png|svg))?)?$"
  [[ $p =~ $icon ]] && return 0
  [[ -n $meta && $p == "usr/share/metainfo/$meta" ]] && return 0
  return 1
}
