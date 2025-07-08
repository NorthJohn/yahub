#!/bin/bash
#
# this setup makes yahub run
#  - from the pi account
#  - in a virtual environment
#  - in the home directory
#
# the development and production are the same.
#


echo "### update and upgrade ###"
sudo apt update
#sudo apt upgrade

echo "### install libraries ###"
sudo apt install python3-pip mosquitto influxdb influxdb-client git

echo "### create venv ###"
cd /home/pi
python3 -m venv py3
source py3/bin/activate

echo "### Installing python requirements ###"
pip3 install pymodbus pyserial pyyaml paho-mqtt influxdb-client python-daemon

echo "### Creating config file ###"
cd  /home/pi/yahub
cp  yahub.config.minimal.yaml yahub.config.yaml

echo "### Get access to serial port ###"
sudo usermod -a -G dialout pi

echo "### Creating run directory ###"
sudo mkdir /run/yahub
sudo chown -R pi:pi /run/yahub

echo "### Setting up systemd ###"
sudo cp yahub.service /etc/systemd/system/
sudo systemctl enable yahub

#echo "### Setting up shutdown  ###"
#sudo cp shutdown-at-dusk.* /etc/systemd/system/
#sudo systemctl enable shutdown-at-dusk



