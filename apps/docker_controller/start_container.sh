#!/bin/bash
sudo docker run -d \
    --restart=always \
    --name registry \
    -p 5000:5000 \
    -v /opt/registry/data:/var/lib/registry registry:2