# Project Setup and Start Guide

## Prerequisites

- Node.js and npm installed ([install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating))

## Installation

```sh
# Install dependencies
npm install
```

## Start Development Server

```sh
# Start the development server
npm run dev
```

The application will be available at **http://localhost:8080/**

## Available Commands

```sh
# Development
npm run dev          # Start development server

# Build
npm run build        # Build for production
npm run build:dev    # Build in development mode
npm run preview      # Preview production build

# Testing
npm run test         # Run tests
npm run test:watch   # Run tests in watch mode

# Linting
npm run lint         # Run ESLint
```

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- shadcn-ui
- Supabase
- React Router
- React Query

## Backend Architecture

This project uses **Supabase** as its backend platform.

### Supabase Client Setup

The Supabase client is initialized in `src/integrations/supabase/client.ts` with:
- Auto-refresh tokens
- LocalStorage session persistence
- TypeScript type safety

**Configuration** (`.env`):
- Project ID: `qrrqgdhvneagmdtqstti`
- URL: `https://qrrqgdhvneagmdtqstti.supabase.co`
- Publishable key for client-side access

### Backend Components

**Database:**
- PostgreSQL database (version 14.1)
- Currently empty schema (ready for tables)
- Supports real-time subscriptions

**Edge Functions (Serverless):**
- Located in `supabase/functions/`
- Written in TypeScript (Deno runtime)
- One function: `analyze-home-issue`

### Edge Function: analyze-home-issue

AI-powered home repair assistant that:
- Accepts text messages and images from frontend
- Sends to Lovable AI Gateway (Google Gemini 2.5 Flash)
- Returns AI-generated repair advice and analysis
- Maintains conversation history (last 6 messages)

**API Call Example** (from `VideoChat.tsx`):
```typescript
const { data, error } = await supabase.functions.invoke("analyze-home-issue", {
  body: {
    message: userMessage.content,
    image: imageData,
    history: messages.slice(-6),
  },
});
```

### Available Supabase Features

- **Authentication**: Ready for implementation (not currently used)
- **Real-time subscriptions**: Available for live data updates
- **File storage**: Available for image/file uploads
- **Row Level Security**: Available for database access control

### How to Extend Backend

**Add database tables:**
1. Create tables in Supabase dashboard
2. Regenerate types: `npm run build`
3. Use in code: `supabase.from('table_name').select()`

**Add edge functions:**
1. Create folder in `supabase/functions/your-function-name/`
2. Add configuration to `supabase/config.toml`
3. Invoke from frontend: `supabase.functions.invoke('your-function-name')`
