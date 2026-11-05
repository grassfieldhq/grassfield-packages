#!/usr/bin/env bash
# Markdown for the CI job summary from the build statistics build-channel.sh leaves (docs/build-caches.md).
#
#   build-summary.sh DIR     DIR holds build.log (makepkg's lines time-stamped "[+Ns]"), and, each optional, steps.tsv,
#                            profile.txt (a process sample every 5 s) and ccache.raw (ccache --print-stats)
#
# Prints: the steps of build-channel.sh with their wall time, the phases of makepkg, the time each CMake build took (from
# the interval between two "Build files have been written" lines: configure of the next, build of the one before), the
# wall time each tool was running (a sample counts 5 s), and the ccache hit rate. Names, times and counters only: no
# environment, no path outside the build tree. Reads only. Exit 0; 2 usage.
set -uo pipefail
d=${1:-}
[[ -d $d ]] || { echo "usage: build-summary.sh DIR" >&2; exit 2; }

if [[ -s $d/steps.tsv ]]; then
  echo "### Steps"
  echo
  echo "| step | seconds |"
  echo "|---|---:|"
  awk -F'\t' 'NR > 1 { printf "| %s | %d |\n", name, $1 - t } { t = $1; name = $2 }' "$d/steps.tsv"
  echo
fi

if [[ -s $d/build.log ]]; then
  echo "### makepkg phases"
  echo
  echo "| phase | seconds |"
  echo "|---|---:|"
  awk '
    match($0, /^\[\+[0-9]+s\] /) {
      t = substr($0, 3, RLENGTH - 5) + 0; text = substr($0, RLENGTH + 1)
      if (text ~ /^==> (Making package|Installing missing dependencies|Retrieving sources|Extracting sources|Starting (prepare|build|check|package[a-z_-]*)\(\)|Tidying install|Creating package|Creating .* package|Cleaning up)/) {
        if (name != "") printf "| %s | %d |\n", name, t - start
        name = text; sub(/^==> /, "", name); start = t
      }
      last = t
    }
    END { if (name != "") printf "| %s | %d |\n", name, last - start }' "$d/build.log"
  echo
  echo "### Time between two CMake configures: the build of the previous directory plus this configure (longest first)"
  echo
  echo "| configured directory | seconds |"
  echo "|---|---:|"
  awk '
    match($0, /^\[\+[0-9]+s\] /) {
      t = substr($0, 3, RLENGTH - 5) + 0; text = substr($0, RLENGTH + 1)
      if (text ~ /^-- Build files have been written to: /) {
        n = text; sub(/^.*\//, "", n)
        if (prev != "") printf "%d\t%s\n", t - pt, n
        prev = n; pt = t
      }
    }' "$d/build.log" | sort -rn | head -n 12 | awk -F'\t' '{ printf "| %s | %d |\n", $2, $1 }'
  echo
fi

if [[ -s $d/profile.txt ]]; then
  echo "### Wall time by tool (samples every 5 s; parallel compiles count once)"
  echo
  echo "| tool | seconds |"
  echo "|---|---:|"
  awk '
    BEGIN {
      split("pacman|pacman -S/-U (install, download); cc1plus|C++ compiler; cc1|C compiler; ld|linker; ninja|ninja; cmake|cmake; qmlcachegen|qmlcachegen; qmlimportscanner|qmlimportscanner; moc|moc; rcc|rcc; lrelease|lrelease; lupdate|lupdate; python3|python (icons composer, scripts); grassfield-wall|wallpaper shrink; rsvg-convert|rsvg-convert (SVG to PNG); zstd|zstd (package compression); bsdtar|bsdtar; strip|strip; git|git; ccache|ccache; gpg|gpg; repo-add|repo-add", pairs, "; ")
      for (i in pairs) { split(pairs[i], kv, "|"); label[kv[1]] = kv[2] }
    }
    { for (i = 2; i <= NF; i++) if ($i in label) seen[$i, NR] = 1; samples = NR
      for (k in label) if ((k, NR) in seen) n[k]++ }
    END { for (k in n) printf "%d\t%s\n", n[k] * 5, label[k] }' "$d/profile.txt" | sort -rn | awk -F'\t' '{ printf "| %s | %d |\n", $2, $1 }'
  echo
fi

if [[ -s $d/ccache.raw ]]; then
  echo "### ccache"
  echo
  awk -F'\t' '
    $1 == "direct_cache_hit" || $1 == "preprocessed_cache_hit" { hit += $2 }
    $1 == "cache_miss" { miss += $2 }
    END {
      if (hit + miss == 0) print "no cacheable compile call"
      else printf "hits %d, misses %d, hit rate %.1f%%\n", hit, miss, 100 * hit / (hit + miss)
    }' "$d/ccache.raw"
  echo
fi
exit 0
