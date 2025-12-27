# Frontend Architecture

## Overview

The frontend is a React-based single-page application (SPA) using Vite as the build tool.

## Technology Stack

- **Framework**: React 18
- **Build Tool**: Vite 7
- **Routing**: React Router DOM 7
- **Styling**:
  - styled-components for component styling
  - Bootstrap 5 with React Bootstrap
  - Bootstrap Icons
- **Type Checking**: TypeScript types for React

## Project Structure [TODO]

```
frontend/
├── public/              # Static assets
├── src/
│   ├── components/      # Reusable UI components
│   │   └── chat-components/
│   │       ├── chat-content/    # Chat message display
│   │       └── chat-sidebar/    # Chat navigation sidebar
│   ├── page/            # Page components
│   │   └── ChatPage/    # Main chat interface
│   ├── App.jsx          # Root application component
│   └── main.jsx         # Application entry point
├── index.html           # HTML template
├── vite.config.js       # Vite configuration
└── package.json         # Dependencies
```

## Current Components

### ChatContent [TODO]
- Displays chat messages and AI assistant interface
- Header bar with AI assistant indicator
- Message input field with send button
- Uses Bootstrap Container/Row layout

### ChatSidebar [TODO]
- Navigation sidebar for chat channels
- styled-components for custom styling

### ChatPage [TODO]
- Main page layout combining sidebar and content
- styled-components for layout styling

## Functional Requirements [TODO]

### Chat Interface
- Display messages in a scrollable container
- Input field for composing messages
- Send button for message submission
- Real-time message updates via WebSocket

### Navigation
- Sidebar showing available chatrooms
- Route-based navigation between pages

## Non-Functional Requirements

### Build & Development
- Hot module replacement via Vite dev server
- ESLint for code linting
- Production build optimization

### Styling
- Component-scoped styles via styled-components
- Responsive design with Bootstrap grid

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server |
| `npm run build` | Build for production |
| `npm run lint` | Run ESLint |
| `npm run preview` | Preview production build |
