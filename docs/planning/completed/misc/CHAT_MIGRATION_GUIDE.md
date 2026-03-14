# 🚀 Chat Hook Migration Guide

## Overview

We've upgraded our chat system with the **Vercel AI SDK** to provide streaming responses, enhanced error handling, and multi-modal capabilities. This guide helps you migrate from the old `useChat` hook to the new `usePortfolioChat` hook.

## Quick Migration

### Before (Old Hook)
```typescript
import { useChat } from '../../features/external';

const {
  messages,
  sendMessage,
  loading,
  clearMessages,
  hasMessages,
  canSend,
  error
} = useChat();
```

### After (New Hook)
```typescript
import { usePortfolioChat } from '../../features/external/hooks/usePortfolioChat';

const {
  messages,
  sendMessage,
  loading,
  clearMessages,
  hasMessages,
  canSend,
  error,
  // 🆕 Enhanced features
  chatStatus,
  stop,
  regenerate,
  editMessage,
  deleteMessage,
  uploadFiles,
  removeFile
} = usePortfolioChat();
```

## Key Differences

### 1. **Streaming Responses**
- **Old**: Messages appeared all at once after completion
- **New**: Messages stream token-by-token in real-time

### 2. **Enhanced Status**
```typescript
// New chatStatus provides rich feedback
if (chatStatus.state === 'streaming') {
  console.log(`Tokens generated: ${chatStatus.progress?.tokensGenerated}`);
} else if (chatStatus.state === 'tool-executing') {
  console.log(`Executing: ${chatStatus.progress?.currentTool}`);
}
```

### 3. **Message Management**
```typescript
// Edit any message
editMessage(messageId, "Updated content");

// Delete messages
deleteMessage(messageId);

// Retry failed messages
retryMessage(messageId);
```

### 4. **File Upload Support**
```typescript
// Upload files for analysis
const handleFileUpload = async (files: FileList) => {
  const attachments = await uploadFiles(files);
  sendMessage({
    text: "Analyze these portfolio documents",
    files: attachments
  });
};
```

### 5. **Advanced Controls**
```typescript
// Stop streaming response
stop();

// Regenerate last response
regenerate();
```

## Migration Checklist

- [ ] Replace `useChat` import with `usePortfolioChat`
- [ ] Update destructuring to include new features (optional)
- [ ] Test streaming functionality
- [ ] Add enhanced status indicators to UI (optional)
- [ ] Implement file upload if needed (optional)
- [ ] Add message management controls (optional)

## Backward Compatibility

✅ **The new hook is 100% backward compatible**

All existing properties and methods work exactly the same:
- `messages`, `sendMessage`, `loading`, `error`
- `clearMessages`, `hasMessages`, `canSend`
- `currentPortfolio`, `chatContext`

You can migrate incrementally and add new features as needed.

## Enhanced Error Handling

The new hook provides intelligent error categorization and auto-retry:

```typescript
// Errors are automatically categorized and retried
if (chatStatus.error?.retryable) {
  // Will auto-retry network/server errors
  console.log(`Retrying in ${chatStatus.error.retryDelay}ms`);
}
```

## File Upload Example

```typescript
const ChatWithFiles = () => {
  const { sendMessage, uploadFiles } = usePortfolioChat();
  
  const handleSendWithFiles = async (text: string, fileList: FileList) => {
    const files = await uploadFiles(fileList);
    sendMessage({ text, files });
  };
  
  return (
    <div>
      <input type="file" onChange={(e) => handleSendWithFiles("Analyze this", e.target.files)} />
    </div>
  );
};
```

## Need Help?

The new hook provides the same interface as the old one, so migration should be seamless. If you encounter any issues:

1. Check that imports are correct
2. Verify all destructured properties are available
3. Test with a simple message first
4. Add enhanced features incrementally

## Components Already Migrated

- ✅ `DashboardContainer.tsx`
- ✅ `ChatInterface.tsx` (uses shared chat context)
- ✅ `AIChat.tsx` (uses shared chat context)

## Next Steps

1. **Test the migration** - Verify chat functionality works
2. **Add enhanced features** - Implement streaming indicators, file upload, etc.
3. **Update UI components** - Take advantage of new status information
4. **Remove old hook** - Once all components are migrated

---

🎉 **Enjoy the enhanced chat experience with streaming, file uploads, and advanced controls!**
