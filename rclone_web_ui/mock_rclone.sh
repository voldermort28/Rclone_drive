#!/bin/bash
echo "Mocking rclone transfer from $3 to $4..."
echo "Transferred: 0 MiB, 0%, 0 MiB/s, ETA 1m"
sleep 1
echo "Transferred: 50 MiB, 50%, 50 MiB/s, ETA 1s"
sleep 1
echo "Transferred: 100 MiB, 100%, 50 MiB/s, ETA 0s"
