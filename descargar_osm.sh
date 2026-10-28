#!/usr/bin/env bash
# Descarga el recuadro del reto (lon -79.030..-78.950, lat -2.930..-2.860)
# en 5x5 teselas desde la API 0.6 de OpenStreetMap (limite: 50 000 nodos
# por peticion). Salida: ~/results/reto/osm/tile_<i>_<j>.osm
set -euo pipefail

LON_MIN=-79.030; LON_MAX=-78.950
LAT_MIN=-2.930;  LAT_MAX=-2.860
N=5
OUT=${1:-$HOME/results/reto/osm}
API=https://api.openstreetmap.org/api/0.6/map
mkdir -p "$OUT"

for i in $(seq 0 $((N-1))); do
  for j in $(seq 0 $((N-1))); do
    read -r W S E NN < <(awk -v a=$LON_MIN -v b=$LON_MAX -v c=$LAT_MIN -v d=$LAT_MAX \
                             -v i=$i -v j=$j -v n=$N 'BEGIN{
      dx=(b-a)/n; dy=(d-c)/n
      printf "%.5f %.5f %.5f %.5f\n", a+i*dx, c+j*dy, a+(i+1)*dx, c+(j+1)*dy }')
    f="$OUT/tile_${i}_${j}.osm"
    if [[ -s "$f" ]] && grep -q "</osm>" "$f"; then
      echo "ya existe $f"; continue
    fi
    echo "tesela ($i,$j): bbox=$W,$S,$E,$NN"
    for intento in 1 2 3; do
      code=$(curl -s -w '%{http_code}' -o "$f" "$API?bbox=$W,$S,$E,$NN") || code=000
      [[ "$code" == 200 ]] && break
      echo "  HTTP $code, reintento $intento en 10 s"; sleep 10
    done
    [[ "$code" == 200 ]] || { echo "ERROR en $f"; rm -f "$f"; exit 1; }
    sleep 1   # no saturar la API publica
  done
done
echo "Listo: $(ls "$OUT"/tile_*.osm | wc -l) teselas en $OUT"
