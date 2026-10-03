#!/bin/bash
cd ~/aakash-gj/deepstream_python_apps/apps/deepstream-nvdsanalytics-peoplenet
cp config_nvdsanalytics_cam6.txt config_nvdsanalytics.txt
python3 deepstream_nvdsanalytics.py "rtsp://65.1.214.31:8554/gj/cam6"
