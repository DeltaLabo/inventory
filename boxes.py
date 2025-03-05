import pandas as pd

detail = pd.read_csv("details.csv")
locati = pd.read_csv("locations.csv")

abox = locati[locati["location"]=="A"]

print(abox)