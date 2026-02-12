"""
Geolocation and ASN lookup context provider.
"""
import asyncio
import logging
import aiohttp
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class GeoIPResolver:
    """Resolves IP addresses to location and ISP information using ip-api.com."""
    
    # 1000 items, ample for a session
    _cache: Dict[str, dict] = {} 
    _batch_url = "http://ip-api.com/batch"
    
    def __init__(self):
        pass

    async def resolve_batch(self, ips: List[str]) -> Dict[str, dict]:
        """
        Resolve a list of IPs to their location details.
        Returns a dict mapping IP -> Info.
        """
        results = {}
        to_query = []

        # Check cache first
        for ip in ips:
            if ip in self._cache:
                results[ip] = self._cache[ip]
            elif self._is_private(ip):
                 results[ip] = {
                     "status": "success",
                     "city": "Local Network",
                     "country": "LAN",
                     "isp": "Private",
                     "org": "",
                     "as": ""
                 }
            else:
                to_query.append(ip)

        if not to_query:
            return results

        # Process in chunks of 90 (API limit is 100, playing it safe)
        chunk_size = 90
        for i in range(0, len(to_query), chunk_size):
            chunk = to_query[i:i + chunk_size]
            try:
                async with aiohttp.ClientSession() as session:
                    # fields: query, status, message, country, regionName, city, isp, org, as
                    async with session.post(
                        self._batch_url,
                        json=chunk,
                        params={"fields": "query,status,message,country,regionName,city,isp,org,as"}
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            for item in data:
                                # ip-api returns the query IP in 'query' field
                                ip = item.get("query")
                                if ip:
                                    self._cache[ip] = item
                                    results[ip] = item
                        else:
                            logger.error(f"GeoIP query failed: {response.status}")
                            
            except Exception as e:
                logger.error(f"Error resolving IPs: {e}")

        return results

    def _is_private(self, ip: str) -> bool:
        """Check if IP is private/local."""
        # Simple check for common private ranges
        if ip.startswith("127.") or ip == "::1": return True
        if ip.startswith("10."): return True
        if ip.startswith("192.168."): return True
        if ip.startswith("172."):
            # 172.16.x.x to 172.31.x.x
            parts = ip.split(".")
            if len(parts) > 1 and 16 <= int(parts[1]) <= 31:
                return True
        return False
