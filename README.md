# O-1--Attendance-Architecture
Optimized classroom attendance latency from $O(N)$ to $O(1)$ by architecting a distributed 'Push' model. Leveraged Hash-Set based filtering to prevent duplicate entries in constant time and implemented a local-storage buffer to bypass $3^{rd}$ party API rate-limiting bottlenecks
