#!/bin/sh

cd /home/ec2-user

# Backup entire datastore
google_appengine/appcfg.py download_data --application=khanexercises --url=http://khanexercises.appspot.com/remote_api --filename=`date +%F.full.dat` --email=kamens@gmail.com --passin < private_pw > `date +%F.full.log`

# Gzip results
gzip -f *.full.dat
gzip -f *.full.log

for f in *.full.*.gz
do
  echo "Moving $f to s3 bucket"
  s3cmd-1.0.0/s3cmd put $f s3://KA-full-backups/$f
done

# Delete files older than 2 weeks
find *.gz -mtime +14 -exec rm {} \;

