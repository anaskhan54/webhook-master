# WebhookMaster

A robust webhook delivery service built to efficiently ingest webhooks, queue them for reliable delivery, manage retries with exponential backoff, and provide comprehensive visibility into delivery statuses.

## Live Deployment

You can access the live deployment at: [https://whmaster.anaskhan.co.in/swagger/](https://whmaster.anaskhan.co.in/swagger/)

## Features

- **Subscription Management**: Create, read, update, and delete webhook subscriptions
- **Webhook Ingestion**: Quickly acknowledge and asynchronously process webhook deliveries
- **Asynchronous Processing**: Background workers handle deliveries without blocking the API
- **Intelligent Retry Mechanism**: Exponential backoff strategy for failed deliveries
- **Comprehensive Logging**: Track every delivery attempt with detailed status information
- **Log Retention Policy**: Automatic cleanup of logs older than 72 hours
- **Status & Analytics**: Endpoints for delivery status and subscription history
- **Performance Optimization**: Redis caching for high-throughput scenarios
- **Event Type Filtering**: Target specific event types to relevant subscriptions
- **Payload Signature Verification**: HMAC-SHA256 verification for webhook integrity

## Architecture Choices

### Framework: Django with Django REST Framework

I chose Django for its robust ORM, built-in authentication, admin interface, and excellent ecosystem. Django REST Framework provides powerful tools for building RESTful APIs with minimal code. The combination enables rapid development while maintaining code quality and security.

### Database: PostgreSQL

PostgreSQL was selected for several reasons:
1. **Reliability**: Mature ACID-compliant database with proven track record
2. **Performance with Large Datasets**: Excellent indexing and query optimization for handling millions of delivery logs
3. **JSON Support**: Native JSONB support for storing webhook payloads
4. **Concurrency**: Handles multiple concurrent connections efficiently, critical for high-volume webhook processing

### Asynchronous Task Processing: Celery with Redis Broker

The webhook delivery system requires reliable asynchronous processing:
1. **Decoupling**: Celery allows complete separation of webhook ingestion from delivery processing
2. **Reliability**: Tasks persist in Redis even if workers crash
3. **Scheduling**: Built-in support for delayed tasks (essential for retry mechanism)
4. **Scalability**: Easy to scale horizontally by adding more worker containers

### Caching Strategy: Redis

Redis is used for:
1. **Subscription Caching**: Frequently accessed subscription data is cached to minimize database lookups
2. **Rate Limiting**: Protects target endpoints from excessive requests during retries
3. **Performance**: In-memory operations for speed-critical components

### Retry Strategy

The retry mechanism uses exponential backoff with the following intervals:
- 1st retry: 10 seconds
- 2nd retry: 30 seconds
- 3rd retry: 1 minute
- 4th retry: 5 minutes
- 5th retry: 15 minutes

This approach:
- Reduces immediate load on potentially failing systems
- Allows temporary issues to resolve naturally
- Balances delivery speed with system resilience

### Containerization: Docker & Docker Compose

The entire application is containerized to ensure consistent environments across development, testing, and production. The multi-container architecture includes:
- Web service container (Django)
- Celery worker container
- Celery beat scheduler container
- PostgreSQL container
- Redis container

## Database Schema and Indexing

### Subscription Model
- `id`: UUID primary key
- `target_url`: URL where webhooks are delivered
- `secret_key`: Optional key for signature verification
- `event_types`: Array of event types the subscription handles
- `is_active`: Boolean flag to enable/disable the subscription
- `created_at`: Timestamp of creation

### Webhook Model
- `id`: UUID primary key
- `subscription`: Foreign key to Subscription
- `payload`: JSONB field containing the webhook data
- `event_type`: String identifying the event type
- `status`: Enum ('PENDING', 'IN_PROGRESS', 'DELIVERED', 'FAILED')
- `created_at`: Timestamp of creation
- `retry_count`: Number of delivery attempts made
- `next_retry_at`: Timestamp for next retry attempt

### DeliveryAttempt Model
- `id`: UUID primary key
- `webhook`: Foreign key to Webhook
- `timestamp`: When the attempt was made
- `attempt_number`: Sequential number of the attempt
- `status_code`: HTTP status code received (if any)
- `error_detail`: Details of failure (if applicable)
- `is_success`: Boolean indicating success/failure

### Indexing Strategy

Careful indexing is crucial for performance with high volumes of webhooks:

1. **Foreign Key Indexes**:
   - Index on `webhook_id` in DeliveryAttempt table
   - Index on `subscription_id` in Webhook table

2. **Status-Based Indexes**:
   - Composite index on `status` and `next_retry_at` for efficient retry queue queries
   - Speeds up queries like "find all PENDING webhooks with next_retry_at <= now()"

3. **Timestamp-Based Indexes**:
   - Index on `created_at` in Webhook table for chronological sorting
   - Index on `timestamp` in DeliveryAttempt for log retention queries
   - Enables efficient pruning of old logs

4. **Event Type Index**:
   - Index on `event_type` for event filtering queries
   - Particularly important with many event types and selective subscriptions

## Setup Instructions

### Prerequisites
- Docker and Docker Compose installed on your system
- Git for cloning the repository
- 4GB+ of available memory for Docker

### Docker Setup (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/webhookmaster.git
   cd webhookmaster
   ```

2. Start the application with Docker Compose:
   ```bash
   docker-compose up -d
   ```

3. Wait for all services to initialize (usually takes 30-60 seconds)

   This will:
   - Start PostgreSQL database for data storage
   - Start Redis for caching and message broker
   - Start the Django application with the development server
   - Start Celery worker and beat scheduler for background tasks
   - Apply database migrations and create an admin user

4. Access the application:
   - API: http://localhost:8000/api/
   - Swagger documentation: http://localhost:8000/swagger/
   - Admin interface: http://localhost:8000/admin/ (username: admin, password: admin)

### Running Tests

Execute the test suite to ensure everything is working correctly:

```bash
docker-compose exec web python WebhookMaster/manage.py test api
```

## API Usage Examples

### Managing Subscriptions

#### Create a Subscription
```bash
curl -X POST http://localhost:8000/api/subscriptions/ \
  -H 'Content-Type: application/json' \
  -d '{
    "target_url": "https://webhook.site/your-unique-id",
    "secret_key": "your-secret-key",
    "event_types": ["order.created", "user.registered"],
    "is_active": true
  }'
```

#### List All Subscriptions
```bash
curl -X GET http://localhost:8000/api/subscriptions/
```

#### Get Subscription Details
```bash
curl -X GET http://localhost:8000/api/subscriptions/YOUR-SUBSCRIPTION-ID/
```

#### Update a Subscription
```bash
curl -X PUT http://localhost:8000/api/subscriptions/YOUR-SUBSCRIPTION-ID/ \
  -H 'Content-Type: application/json' \
  -d '{
    "target_url": "https://webhook.site/new-id",
    "secret_key": "updated-secret-key",
    "event_types": ["order.created", "order.updated"],
    "is_active": true
  }'
```

#### Delete a Subscription
```bash
curl -X DELETE http://localhost:8000/api/subscriptions/YOUR-SUBSCRIPTION-ID/
```

### Ingesting Webhooks

#### Basic Webhook Ingestion
```bash
curl -X POST http://localhost:8000/api/ingest/YOUR-SUBSCRIPTION-ID/?event_type=order.created \
  -H 'Content-Type: application/json' \
  -d '{
    "order_id": 12345,
    "customer": {"id": 789, "name": "John Doe"},
    "amount": 99.95,
    "items": [{"sku": "PROD-1", "quantity": 2}]
  }'
```

#### Webhook with Signature Verification
```bash
# The signature is an HMAC-SHA256 of the payload using the subscription's secret key
PAYLOAD='{"order_id":12345,"customer":{"id":789,"name":"John Doe"},"amount":99.95}'
SECRET="your-secret-key"
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -X POST http://localhost:8000/api/ingest/YOUR-SUBSCRIPTION-ID/?event_type=order.created \
  -H 'Content-Type: application/json' \
  -H "X-Hub-Signature-256: sha256=$SIGNATURE" \
  -d "$PAYLOAD"
```

### Checking Status and History

#### Get Webhook Delivery Status
```bash
curl -X GET http://localhost:8000/api/status/YOUR-WEBHOOK-ID/
```

#### Get Delivery History for a Subscription
```bash
curl -X GET http://localhost:8000/api/subscriptions/YOUR-SUBSCRIPTION-ID/history/
```

## Deployment Cost Estimation

Based on the requirement of handling 5,000 webhooks per day with an average of 1.2 delivery attempts per webhook:

- **Monthly webhook volume**: 5,000 × 30 = 150,000 webhooks
- **Monthly delivery attempts**: 150,000 × 1.2 = 180,000 attempts

### AWS Free Tier Cost Breakdown

| Resource | Specification | Monthly Usage | Free Tier Allowance | Cost Beyond Free Tier |
|----------|---------------|---------------|---------------------|----------------------|
| EC2 Instance | t2.micro | 730 hours | 750 hours | $0 |
| RDS PostgreSQL | db.t3.micro | 730 hours | 750 hours | $0 |
| ElastiCache Redis | cache.t3.micro | 730 hours | 0 hours | ~$13.14 |
| EBS Storage | 20 GB | 20 GB | 30 GB | $0 |
| Data Transfer | ~5 GB | 5 GB | 100 GB | $0 |

**Estimated Monthly Cost**: Approximately $13.14 USD

### Scaling Considerations

At higher volumes, costs would increase primarily due to:
1. Larger/more EC2 instances for workers
2. Larger RDS instance for database
3. Increased ElastiCache capacity
4. Additional data transfer costs

## Assumptions Made

1. **Network Reliability**: The system assumes that most delivery failures are temporary and can be resolved with retries.

2. **Target Endpoint Behavior**: The system expects target endpoints to follow standard HTTP practices, returning appropriate status codes to indicate success/failure.

3. **Payload Size**: Assumed average payload size of 5-10KB. Extremely large payloads may require adjustments to the system.

4. **Webhook Volume Distribution**: Assumed relatively even distribution of webhooks throughout the day rather than extreme spikes.

5. **Security Context**: The system implements signature verification but assumes it operates within a secure network environment.

6. **State Recovery**: In case of system failure, webhooks in "IN_PROGRESS" state will be detected and reprocessed by the cleanup task.

7. **Clock Synchronization**: The system assumes reasonable clock synchronization between components for time-based operations.

## Credits and Acknowledgements

### Core Technologies
- [Django](https://www.djangoproject.com/) - Web framework
- [Django REST Framework](https://www.django-rest-framework.org/) - API toolkit
- [Celery](https://docs.celeryq.dev/) - Distributed task queue
- [Redis](https://redis.io/) - In-memory database and message broker
- [PostgreSQL](https://www.postgresql.org/) - Relational database

### Libraries and Tools
- [drf-yasg](https://github.com/axnsan12/drf-yasg) - Swagger/OpenAPI documentation
- [requests](https://requests.readthedocs.io/) - HTTP library
- [docker & docker-compose](https://www.docker.com/) - Containerization
- [psycopg2](https://www.psycopg.org/) - PostgreSQL adapter for Python
- [gunicorn](https://gunicorn.org/) - WSGI HTTP server

### Development Resources
- [Django Documentation](https://docs.djangoproject.com/)
- [Celery Documentation](https://docs.celeryq.dev/)
- [Docker Documentation](https://docs.docker.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

## License

This project is licensed under the MIT License - see the LICENSE file for details. 