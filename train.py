import torch
import torch.multiprocessing as mp
from ultralytics import YOLO

if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)   # explicitly set spawn method
    
    model = YOLO("yolov8n.pt")
    results = model.train(
        data      = "fod_dataset/data.yaml",
        epochs    = 80,
        imgsz     = 640,
        batch     = 32,
        device    = 0,
        name      = "fod_v1",
        patience  = 15,
        workers   = 4,         # back to 4 workers — multiprocessing now explicit
        cache     = "disk",
        amp       = True,
        optimizer = "SGD",
        cos_lr    = True,
    )