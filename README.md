
# Espyresso


## 
```
sudo pacman -S python-pygame
sudo apt-get install python-dev
```

## Pigpiod
[http://abyz.me.uk/rpi/pigpio/download.html](http://abyz.me.uk/rpi/pigpio/download.html)
```
pacman -S wget make gcc
wget abyz.me.uk/rpi/pigpio/pigpio.tar
tar xf pigpio.tar
cd PIGPIO
make
sudo make install
```

To start daemon:
`sudo pigpiod`

### Errors
[https://lonesysadmin.net/2013/02/22/error-while-loading-shared-libraries-cannot-open-shared-object-file/](https://lonesysadmin.net/2013/02/22/error-while-loading-shared-libraries-cannot-open-shared-object-file/)
```
echo "/usr/local/lib" | sudo tee -a /etc/ld.so.conf
sudo ldconfig
```


## Systemd
```
ln -S something
```