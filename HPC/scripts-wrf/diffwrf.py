from netCDF4 import Dataset
import sys
import numpy as np
from scipy.stats import skew
from scipy.stats import norm 
import os.path

import matplotlib.mlab as mlab
import matplotlib.pyplot as plt

import pylab


if len(sys.argv) != 3:
        print (" ")
        print ('Usage: ' + sys.argv[0] + ' <filename1.nc>  <filename2.nc>')
        print (" ")
        sys.exit(1)

if os.path.exists(sys.argv[1]):
        print ('Found ' + sys.argv[1])
else:
        print (" ")
        print ('File does not exist: ' + sys.argv[1])
        print (" ")
        sys.exit(2)

if os.path.exists(sys.argv[2]):
        print ('Found ' + sys.argv[2])
else:
        print (" ")
        print ('File does not exist: ' + sys.argv[2])
        print (" ")
        sys.exit(3)

o = Dataset(sys.argv[1])
p = Dataset(sys.argv[2])

importantVars = [ 'U', 'V', 'W', 'T', 'PH', 'QVAPOR', 'TSLB', 'MU', 'TSK', 'RAINC', 'RAINNC' ]

print (" ")
print ("Differences of the output from two WRF model simulations for a few important fields")
print ("Variable Name                Minimum      Maximum      Average      Std Dev        Skew")
print ("=========================================================================================")
for v in importantVars:
	diffs = p.variables[v][:] - o.variables[v][:]
	print ('{0:24s} {1:12g} {2:12g} {3:12g} {4:12g} {5:12g}'.format(v, np.min(diffs[:]),np.max(diffs[:]),np.mean(diffs[:]),np.std(diffs[:]),skew(diffs[:],axis=None)))

	x = np.reshape(diffs,-1)
	n, bins, patches = plt.hist(x, 200, density=True, facecolor='green', alpha=0.75)

	# add a 'best fit' line
	y = norm.pdf( bins, np.mean(diffs[:]), np.std(diffs[:]))
	l = plt.plot(bins, y, 'r--', linewidth=1)

	plt.xlabel('Difference of ' + o.variables[v].name + ' (' + o.variables[v].units + '), points = ' + str(len(x)))
	plt.ylabel('Probability (%)')
	plt.title(r'$\mathrm{Histogram:}\ \mu=$'+str(np.mean(diffs[:]))+'$,\ \sigma=$'+str(np.std(diffs[:])))

	plt.axis([np.min(diffs[:]), np.max(diffs[:]), 0, 50])
#	plt.axis([np.mean(diffs[:])-8*np.std(diffs[:]), np.mean(diffs[:])+8*np.std(diffs[:]), 0, 50])
	plt.grid(True)

	#plt.show()

	pylab.savefig( o.variables[v].name + '.png', bbox_inches='tight')
	pylab.close()
