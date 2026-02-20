import asyncio
from datetime import datetime
import pandas as pd

from app.services.sr_detection import SRDetectionService
from app.models.market import MarketData, OHLCV

async def main():
    service = SRDetectionService()
    
    # generate some dummy data for a consolidating market
    base_price = 1.0850
    candles = []
    
    import math
    for i in range(500):
        # Sine wave to create consolidation peaks
        price = base_price + math.sin(i / 10.0) * 0.005
        # Add some noise
        import random
        price += (random.random() - 0.5) * 0.001
        
        candles.append(OHLCV(
            timestamp=datetime.utcnow(),
            open=price,
            high=price + 0.0005,
            low=price - 0.0005,
            close=price,
            volume=100
        ))
        
    data = MarketData(
        ticker="EURUSD",
        timeframe="15m",
        data=candles
    )
    
    zones = await service.detect_zones(data)
    
    print(f"Detected {len(zones)} zones:")
    for z in zones:
        print(f"Level: {z.level:.4f}, Range: {z.price_range}, Touches: {z.touches}, Dist to Current: {z.distance_to_current:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
