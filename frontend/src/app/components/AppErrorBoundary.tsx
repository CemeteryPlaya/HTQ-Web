import { Component, type ErrorInfo, type ReactNode } from 'react';

import { reportClientError } from '@/lib/telemetry';

interface AppErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

interface AppErrorBoundaryProps {
  children: ReactNode;
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  constructor(props: AppErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo);
    reportClientError({
      message: error.message,
      stack: error.stack,
      componentStack: errorInfo.componentStack ?? undefined,
      url: window.location.href,
    });
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen flex items-center justify-center bg-red-50 p-4">
        <div className="max-w-md w-full bg-white p-8 rounded-lg shadow-lg border border-red-200">
          <h1 className="text-2xl font-bold text-red-600 mb-4">Something went wrong</h1>
          <p className="text-gray-700 mb-4">The application crashed while rendering this page.</p>
          <pre className="bg-gray-100 p-4 rounded text-xs overflow-auto max-h-40 mb-4">
            {this.state.error?.toString()}
          </pre>
          <button
            onClick={() => window.location.reload()}
            className="w-full py-2 px-4 bg-red-600 text-white rounded hover:bg-red-700 transition"
          >
            Reload Page
          </button>
        </div>
      </div>
    );
  }
}
