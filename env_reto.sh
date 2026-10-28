# Entorno del reto: SUMO 1.28 + traci/sumolib/pandas/matplotlib instalados con
# pip --target en ~/results/reto/.pylib (persiste en el bind mount del host).
# Uso dentro del contenedor:  source ~/results/reto/env_reto.sh
L=$HOME/results/reto/.pylib
export PYTHONPATH=$L${PYTHONPATH:+:$PYTHONPATH}
export PATH=$L/bin:$PATH
export SUMO_HOME=$L/sumo
alias randomTrips.py="python3 $SUMO_HOME/tools/randomTrips.py"
