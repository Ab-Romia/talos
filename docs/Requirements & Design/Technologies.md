# Technologies and Tools

This section outlines key technologies and tools utilized in our project.
Overview of their purpose and reasoning for selection.

The choices are mainly based on:

- development speed,
- compatibility with project requirements,
- and our team's preferences and prior experiences.

They can be revisited and changed as needed during development.

## Frontend

For the main frontend framework, we have considered the following options:

| Framework                      | Pros                                                                                                                                                                                                                           | Cons                                                                                                                                    |
|--------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| [React](https://reactjs.org/)  | - Large ecosystem and community support<br>- Compatibility with various UI libraries<br>- Component-based architecture for reusability<br>- Suitable for building dynamic web applications<br>- Familiarity among team members | - Slower performance compared alternatives<br>- Requires additional libraries for state management and routing<br>- Large bundle sizes  |
| [Angular](https://angular.io/) | - Comprehensive framework with built-in features<br>- Strong support for large-scale applications<br>- Backed by Google<br>- Two-way data binding                                                                              | - Steeper learning curve<br>- Verbose syntax<br>- Larger bundle sizes<br>- Less flexibility compared to libraries like React and Vue.js |
| [Vue.js](https://vuejs.org/)   | - Lightweight and fast<br>- Easy to learn and integrate<br>- Flexible and modular architecture<br>- Strong community support                                                                                                   | - Smaller ecosystem compared to React<br>- Less suitable for large-scale applications<br>- Limited corporate backing                    |

React has been selected as the primary frontend framework due to its large ecosystem, component-based architecture, and
familiarity among team members.

State management will be handled using [Redux](https://redux.js.org/), which provides a predictable state container for
JavaScript apps,
facilitating easier debugging and testing.

For UI component libraries, we have chosen to use [Material-UI (MUI)](https://mui.com/) due to its comprehensive set of
pre-designed
components, ease of customization, and strong community support.
[TailwindCSS](https://tailwindcss.com/) is also considered for utility-first styling, allowing for rapid UI development
with a focus on design
consistency.
[Bootstrap](https://getbootstrap.com/) is another option, but MUI and TailwindCSS provide more flexibility and modern
design options.

## Communication

For serializing structured data, we will
use [Protocol Buffers (Protobuf)](https://developers.google.com/protocol-buffers/docs/overview / https://github.com/protocolbuffers/protobuf)
instead of the widely used JSON format.
Protobuf offers several advantages, including *smaller message sizes*, *faster serialization/deserialization*, and
*strong typing*,
better performance and better scalability for our application's communication needs at the cost of human readability.

For real-time chat functionality, we will
use [WebSockets](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API), which allows for full-duplex
communication channels over a
single TCP connection.

For audio and video communication, we will utilize [WebRTC](https://webrtc.org/), a powerful technology that enables
peer-to-peer
communication directly between browsers and devices.

## Backend

| Backend Option                              | Language / Runtime                                      | Pros                                                                                                                                                          | Cons                                                                                                                                                                                                 |
|---------------------------------------------|---------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [FastAPI](https://fastapi.tiangolo.com/)    | Python / [ASGI](https://asgi.readthedocs.io/en/latest/) | - High performance (async-first)<br>- Modern, easy-to-use and well-documented<br>- Excellent for building APIs and microservices<br                           | - Younger ecosystem compared to Django<br>- Fewer batteries-included features (auth/admin)<br>- Some packages may be sync-first and need adaptation                                                  |
| [Django](https://www.djangoproject.com/)    | Python / [WSGI](https://wsgi.readthedocs.io/en/latest/) | - Mature, batteries-included (ORM, admin, auth)<br>- Large ecosystem and community<br>- Good for large, monolithic web apps                                   | - Heavier and more opinionated<br>- Steeper learning curve for customization<br>- Historically sync-first (async support evolving)                                                                   |
| [Flask](https://flask.palletsprojects.com/) | Python / WSGI                                           | - Lightweight and very flexible<br>- Easy to get started and extend with extensions<br>- Good for simple APIs and microservices                               | - You must assemble many components yourself<br>- Not async-first (requires extra work for async)<br>- Less structure for large projects                                                             |
| [Express](https://expressjs.com/)           | JavaScript / Node.js                                    | - JavaScript on both client and server (unified stack)<br>- Huge ecosystem (npm) and many middleware options<br>- Non-blocking I/O model for high concurrency | - Ecosystem fragmentation and varying package quality<br>- More manual setup for features that frameworks provide<br>- Security pitfalls and callback/async complexity (mitigated by promises/async) |
| [Next.js](https://nextjs.org/)              | JavaScript or Typescript / Node.js (React)              | - Full-stack React framework with SSR/SSG and API routes<br>- Excellent for SEO and hybrid rendering strategies<br>- Built-in optimizations and developer DX  | - Tightly coupled to React and frontend concerns<br>- Less suitable for non-HTTP workloads or heavy backend logic<br>- Runtime and deployment tied to Node environment                               |

FastAPI has been selected as the primary backend framework due to its performance, modern features.
As it is a Python library, it is easy integrated with AI/ML libraries and tools.

### RAG & LLM System

For the Retrieval-Augmented Generation (RAG) system, we will
use [LangChain](https://github.com/langchain-ai/langchain) as the primary framework.
LangChain provides a modular and flexible approach to building RAG systems, with support for various LLMs, vector
databases, and retrieval methods.

For vector database and similarity search, we will
use [Milvus](https://milvus.io/) (specifically [pymilvus](https://github.com/milvus-io/pymilvus)),
an open-source vector database designed for scalability and high performance.

[//]: # (TODO: Continue)

## Database

Below are added comparisons to help justify the choices and surface trade-offs for alternative architectures.

### Relational vs Document databases

| Aspect       | Relational Databases                                                                                 | Document Databases                                                                                     |
|--------------|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------|
| Data model   | Structured tables, rows, and fixed schemas (relations).                                              | Semi-structured JSON-like documents (flexible schema per document).                                    |
| Schema       | Rigid schema with migrations; strong typing.                                                         | Schema-less or schema-flexible; fields can vary between documents.                                     |
| Querying     | SQL: powerful joins, aggregations, and ACID transactions.                                            | Document-oriented queries; indexing and some aggregation, joins are limited or emulated.               |
| Transactions | Mature ACID transactions across multiple rows/tables.                                                | Limited multi-document ACID support (varies by vendor); often eventual consistency for sharded writes. |
| Scalability  | Vertical scaling common; horizontal scaling via sharding or read replicas (more operational effort). | Designed for horizontal scaling and sharding; easier to distribute writes/read across nodes.           |
| Use cases    | Structured data, complex relationships, financial systems, OLTP.                                     | Flexible/rapidly evolving schemas, content stores, user profiles, logging, caching.                    |

### Comparison of several relational databases

| Database                              | Strengths                                                                                                     | Notable limitations                                                                     | Typical use cases                                                                                     |
|---------------------------------------|---------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [PostgreSQL](https://postgresql.org/) | - Advanced SQL features<br>- extensions (PostGIS)<br>- JSONB<br>- strong concurrency and standards compliance | - Heavier than embedded DBs<br>- Operational overhead for high-scale distributed setups | - Complex transactional systems<br>- Analytics<br>- Geospatial<br>- When advanced features are needed |
| [MySQL](https://www.mysql.com/)       | - Mature<br>- widely-supported<br>- Fast for simple read-heavy workloads                                      | - Historically less advanced SQL feature set than Postgres<br>- Replication caveats     | - Web apps<br>- LAMP stack<br>- Read-replicated systems                                               |   
| [MariaDB](https://mariadb.org/)       | - Drop-in MySQL alternative<br>- Some performance and feature enhancements                                    | - Compatibility differences vs MySQL for some features                                  | - Web apps<br>- Replacement for MySQL                                                                 |   
| [SQLite](https://sqlite.org/)         | - Extremely lightweight<br>- Zero-config<br>- Fast for local or embedded use                                  | - Not suited for high-concurrency multi-client production workloads                     | - Local caches<br>- Prototypes<br>- Mobile apps<br>- Testing                                          |   

A relational database is preferred for this project due to the structured nature of the data, need for complex
queries, and strong consistency requirements.
A semi-structured approach can be accommodated using JSON fields within a relational database.

We will mainly use [PostgreSQL](https://postgresql.org/) for this project due to its combination of reliability,
advanced capabilities (including JSONB for semi-structured needs), and strong tooling.

[SQLite](https://sqlite.org/) will be used for local storage and in-memory caching due to its lightweight nature and
ease of use.

[SQLAlchemy](https://sqlalchemy.org/) is a Python SQL toolkit and Object Relational Mapper (ORM), supports multiple
database backends including PostgreSQL and SQLite.
which match our project's requirements.

