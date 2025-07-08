#!/bin/bash
#
#
# download this file into the home directory and run it
#
#   bash setup.sh
#
# this setup makes yahub run
#  - from the users account
#  - in a virtual environment
#  - in the home directory
#
# the development and production environment are one and the same.
#


echo "### update and upgrade ###"
sudo apt update
sudo apt upgrade

echo "### install libraries ###"
sudo apt install python3-pip mosquitto influxdb influxdb-client git

echo "### create venv ###"
cd $HOME
python3 -m venv py3
source py3/bin/activate

echo "### Installing python requirements ###"
pip3 install pymodbus pyserial pyyaml paho-mqtt influxdb-client python-daemon

echo "### Grab yahub and create yahub dir ###"
git clone https://github.com/NorthJohn/yahub.git

echo "### Creating config file ###"
cd  $HOME/yahub
cp  yahub.config.minimal.yaml yahub.config.yaml

echo "### Get access to serial port ###"
sudo usermod -a -G dialout pi

echo "### Creating run directory ###"
sudo mkdir /run/yahub
sudo chown -R pi:pi /run/yahub

echo "### Setting up systemd ###"
sudo cp yahub.service /etc/systemd/system/
sudo systemctl enable yahub

#echo "### Setting up shutdown before solar inverters shut the power off  ###"
#sudo cp shutdown-at-dusk.* /etc/systemd/system/
#sudo systemctl enable shutdown-at-dusk


