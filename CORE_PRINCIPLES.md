# Trippy: Core Principles & Architecture

## Vision
To build a comprehensive travel companion app that integrates flight tracking (like Flighty), reservation management, shared expenses (like Splitwise), and shared photo albums, ensuring a unified and seamless travel experience.

## Core Principles

1. **API-First & Self-Hosted Infrastructure**
   - The entire platform will be built with a robust, well-documented API as the foundational layer.
   - The architecture is designed to be **Self-Hosted**, allowing users to host their own API and infrastructure. The mobile app will simply connect to the user's provided API endpoint.
   - All clients (iOS, Android, Web) will be treated as first-class citizens consuming this API.
   - The API will be designed to be stateless, scalable, and versioned from day one.

2. **Modularity & Scalability**
   - **Flight Tracking:** Real-time data integration for flights.
   - **Reservation Management:** Parsing and organizing hotel, car rental, and event bookings.
   - **Financials (Splitwise-like):** Tracking shared expenses, receipt parsing, and balance settlement.
   - **Media (Native Integration):** Instead of hosting and managing multimedia files on our own infrastructure, the app will cleverly link to existing native photo APIs (e.g., Apple Photos, Google Photos). The API will only store metadata or deep links, saving massive amounts of storage and complexity.

3. **Data Privacy & Security**
   - Secure authentication (e.g., OAuth2, JWT).
   - Strict access control for shared trips and financial data.
   - End-to-end encryption for sensitive documents (like receipts and booking confirmations).

4. **Offline-First & Sync Capabilities**
   - The API will support robust synchronization protocols to allow mobile clients to function offline during flights and sync seamlessly once reconnected.

## Proposed Technology Stack

- **Backend / API Layer:** Python (FastAPI). Lightweight and ideal for self-hosting.
- **Database:** SQLite (default for easy self-hosting) or PostgreSQL (for power users).
- **Storage:** None required for media! We rely on native OS APIs (iOS/Android) for photos/receipts.
- **API Documentation:** Swagger / OpenAPI specification.
- **Mobile Client:** iOS (SwiftUI) connecting to the user's custom API endpoint.

## Next Steps
1. Define the database schema (Users, Trips, Flights, Expenses) using SQLAlchemy.
2. Build core API endpoints for tracking and syncing data.
3. Design the iOS networking layer to allow users to input their self-hosted API URL.
