# RFC: Git Notes Support

## Summary

Add support for git notes, enabling users to attach arbitrary metadata to git objects (typically commits) without modifying the objects themselves. This feature is used by tools like Argo CD to track hydration metadata and by developers for code review annotations.

## Motivation

### Use Cases

1. **Argo CD Hydrator**: Argo CD uses git notes to track which commits have been "hydrated" (processed). They store JSON payloads like `{"drySha": "abc123"}` attached to commit SHAs in custom namespaces (e.g., `refs/notes/hydrator.metadata`). Currently, they shell out to the `git` CLI because go-git lacks this functionality.

   > **Reference**: See Argo CD's implementation:
   > - [`util/git/client.go`](https://github.com/argoproj/argo-cd/blob/master/util/git/client.go) - `GetCommitNote()` and `AddAndPushNote()` methods (lines 1124-1216)
   > - [`commitserver/commit/hydratorhelper.go`](https://github.com/argoproj/argo-cd/blob/master/commitserver/commit/hydratorhelper.go) - `IsHydrated()` and `AddNote()` functions (lines 219-255)

2. **Code Review Tools**: Many workflows use git notes to attach review comments, CI/CD results, or approval signatures to commits.

3. **Build Metadata**: Recording build information, test results, or deployment status against specific commits.

4. **Audit Trails**: Attaching compliance or audit information to commits without modifying history.

### Expected Outcome

- Users can read, write, and remove notes on any git object
- Support for custom note namespaces (not just the default `refs/notes/commits`)
- Full compatibility with notes created by the git CLI
- Notes created by go-git are readable by the git CLI

## Detailed Design

### Git Upstream Reference

This implementation is based on the git C implementation. Key source files in the [git repository](https://github.com/git/git):

| Git File | Description | Relevant Functions |
|----------|-------------|-------------------|
| [`notes.h`](https://github.com/git/git/blob/master/notes.h) | Public API header | `struct notes_tree`, `combine_notes_fn` typedef |
| [`notes.c`](https://github.com/git/git/blob/master/notes.c) | Core implementation | `init_notes()`, `add_note()`, `get_note()`, `remove_note()`, `for_each_note()`, `write_notes_tree()` |
| [`builtin/notes.c`](https://github.com/git/git/blob/master/builtin/notes.c) | CLI commands | `add()`, `list()`, `remove()`, `show()` |

### Git Notes Storage Model

> **Git Reference**: See `notes.c` lines 18-62 for the internal tree structure documentation.

Git notes are stored as:
1. A reference at `refs/notes/<namespace>` (default: `refs/notes/commits`)
2. The reference points to a tree object
3. Tree entries map object SHAs to blob SHAs containing note content
4. For scalability, git uses fanout (e.g., `ab/cd/1234...` instead of `abcd1234...`)

The git implementation uses a 16-tree structure (see `struct int_node` in `notes.c:30-32`) where each internal node has 16 children indexed by SHA nibbles. Leaf nodes (`struct leaf_node` in `notes.c:44-47`) store the mapping from object SHA to note blob SHA.

### Phase 1: Core Data Structures

**File**: `plumbing/object/note.go`

> **Git Reference**: Based on `struct notes_tree` in [`notes.h:52-60`](https://github.com/git/git/blob/master/notes.h#L52-L60) and `struct leaf_node` in [`notes.c:44-47`](https://github.com/git/git/blob/master/notes.c#L44-L47)

```go
package object

import (
    "github.com/go-git/go-git/v6/plumbing"
    "github.com/go-git/go-git/v6/plumbing/storer"
)

var (
    // ErrNoteNotFound is returned when a note does not exist for an object.
    ErrNoteNotFound = errors.New("note not found")
    // ErrNoteExists is returned when trying to add a note that already exists
    // without the force option.
    ErrNoteExists = errors.New("note already exists")
)

// Note represents a git note attached to an object.
// This corresponds to git's leaf_node (notes.c:44-47) which maps
// an object SHA (key_oid) to a note blob SHA (val_oid).
type Note struct {
    // Hash of the blob containing the note content.
    Hash plumbing.Hash
    // Target is the hash of the object this note annotates.
    Target plumbing.Hash
    // Message is the note content.
    Message string
}

// NoteTree represents a collection of notes stored in a tree structure.
// This corresponds to git's struct notes_tree (notes.h:52-60).
// It provides methods to read, add, remove, and iterate over notes.
type NoteTree struct {
    // Ref is the notes reference (e.g., "refs/notes/commits").
    // Corresponds to notes_tree.ref
    Ref plumbing.ReferenceName
    // TreeHash is the current root tree hash (zero hash if empty).
    TreeHash plumbing.Hash

    s       storer.EncodedObjectStorer
    rs      storer.ReferenceStorer
    notes   map[plumbing.Hash]*Note  // object hash -> note (lazy loaded)
    loaded  bool
    dirty   bool  // Corresponds to notes_tree.dirty
}
```

**Tests** (`plumbing/object/note_test.go`):

```go
func TestNote_Basic(t *testing.T) {
    // Test Note struct creation and properties
}

func TestNoteTree_InitEmpty(t *testing.T) {
    // Test creating an empty NoteTree
}

func TestNoteTree_InitFromExistingRef(t *testing.T) {
    // Test loading NoteTree from existing refs/notes/commits
}
```

### Phase 2: Get Note

> **Git Reference**: Corresponds to [`get_note()`](https://github.com/git/git/blob/master/notes.c#L1173-L1182) in `notes.c` which calls `note_tree_find()` ([`notes.c:149-160`](https://github.com/git/git/blob/master/notes.c#L149-L160))

```go
// Get retrieves the note for the given object hash.
// Returns ErrNoteNotFound if no note exists for the object.
func (nt *NoteTree) Get(objectHash plumbing.Hash) (*Note, error)
```

The implementation must handle git's fanout structure. Git can store notes at various path depths:
- Flat: `aabbccdd1122334455...` (full 40-char hex)
- 2-char fanout: `aa/bbccdd1122334455...`
- 4-char fanout: `aa/bb/ccdd1122334455...`
- And so on...

```go
// pathsFromHash returns all possible tree paths for an object hash.
// Git may use different fanout levels, so we check multiple patterns.
func pathsFromHash(h plumbing.Hash) []string {
    hex := h.String()
    return []string{
        hex,                                    // no fanout
        hex[:2] + "/" + hex[2:],               // 2-char fanout  
        hex[:2] + "/" + hex[2:4] + "/" + hex[4:], // 4-char fanout
        // Additional levels can be added if needed
    }
}
```

**Tests**:

```go
func TestNoteTree_Get_NotFound(t *testing.T) {
    // Returns ErrNoteNotFound for non-existent note
}

func TestNoteTree_Get_FlatPath(t *testing.T) {
    // Retrieves note stored without fanout
}

func TestNoteTree_Get_FanoutPath(t *testing.T) {
    // Retrieves note stored with 2-char fanout
}

func TestNoteTree_Get_DeepFanoutPath(t *testing.T) {
    // Retrieves note stored with 4-char fanout
}
```

### Phase 3: Add Note

> **Git Reference**: Corresponds to [`add_note()`](https://github.com/git/git/blob/master/notes.c#L1140-L1154) in `notes.c` which calls `note_tree_insert()` ([`notes.c:253-327`](https://github.com/git/git/blob/master/notes.c#L253-L327))

The combination functions are defined in [`notes.h:30-41`](https://github.com/git/git/blob/master/notes.h#L30-L41) and implemented in [`notes.c:810-948`](https://github.com/git/git/blob/master/notes.c#L810-L948):
- `combine_notes_concatenate()` - default, appends notes
- `combine_notes_overwrite()` - replaces existing note
- `combine_notes_ignore()` - keeps existing note
- `combine_notes_cat_sort_uniq()` - concatenate, sort lines, remove duplicates

```go
// CombineNotesFunc defines how to combine existing and new notes.
// This corresponds to git's combine_notes_fn typedef (notes.h:30-31).
type CombineNotesFunc func(existing, new string) (string, error)

// Predefined combination strategies matching git's behavior.
// See notes.c:810-948 for the C implementations.
var (
    // CombineNotesOverwrite replaces existing note with new note.
    // Corresponds to combine_notes_overwrite() in notes.c:857-861
    CombineNotesOverwrite CombineNotesFunc = func(_, new string) (string, error) {
        return new, nil
    }
    
    // CombineNotesConcatenate appends new note to existing note.
    // Corresponds to combine_notes_concatenate() in notes.c:810-854
    CombineNotesConcatenate CombineNotesFunc = func(old, new string) (string, error) {
        if old == "" {
            return new, nil
        }
        return old + "\n" + new, nil
    }
    
    // CombineNotesIgnore keeps the existing note, ignoring the new one.
    // Corresponds to combine_notes_ignore() in notes.c:864-868
    CombineNotesIgnore CombineNotesFunc = func(old, _ string) (string, error) {
        return old, nil
    }
)

// Add adds or updates a note for the given object.
// If a note already exists and combine is nil, returns ErrNoteExists.
// If combine is provided, it's used to merge existing and new content.
// An empty message removes the note.
func (nt *NoteTree) Add(objectHash plumbing.Hash, message string, combine CombineNotesFunc) error
```

**Tests**:

```go
func TestNoteTree_Add_New(t *testing.T) {
    // Successfully adds note to object without existing note
}

func TestNoteTree_Add_OverwriteWithCombine(t *testing.T) {
    // Overwrites existing note when CombineNotesOverwrite is used
}

func TestNoteTree_Add_FailsWithoutCombine(t *testing.T) {
    // Returns ErrNoteExists when note exists and combine is nil
}

func TestNoteTree_Add_Concatenate(t *testing.T) {
    // Concatenates notes when CombineNotesConcatenate is used
}

func TestNoteTree_Add_EmptyRemoves(t *testing.T) {
    // Adding empty message removes the note
}

func TestNoteTree_Add_MarksDirty(t *testing.T) {
    // Adding note sets dirty flag
}
```

### Phase 4: Remove Note

> **Git Reference**: Corresponds to [`remove_note()`](https://github.com/git/git/blob/master/notes.c#L1157-L1170) in `notes.c` which calls `note_tree_remove()` ([`notes.c:202-238`](https://github.com/git/git/blob/master/notes.c#L202-L238))

```go
// Remove removes the note for the given object.
// Returns ErrNoteNotFound if no note exists.
func (nt *NoteTree) Remove(objectHash plumbing.Hash) error
```

**Tests**:

```go
func TestNoteTree_Remove_Existing(t *testing.T) {
    // Successfully removes existing note
}

func TestNoteTree_Remove_NotFound(t *testing.T) {
    // Returns ErrNoteNotFound for non-existent note
}

func TestNoteTree_Remove_MarksDirty(t *testing.T) {
    // Removing note sets dirty flag
}
```

### Phase 5: Iterate Notes

> **Git Reference**: Corresponds to [`for_each_note()`](https://github.com/git/git/blob/master/notes.c#L1185-L1191) in `notes.c` and the `each_note_fn` callback typedef ([`notes.h:214-216`](https://github.com/git/git/blob/master/notes.h#L214-L216))

```go
// NoteIter provides iteration over notes in a NoteTree.
type NoteIter struct {
    notes []*Note
    pos   int
}

// Next returns the next note. Returns io.EOF when iteration is complete.
func (iter *NoteIter) Next() (*Note, error)

// ForEach calls fn for each note. Stops early if fn returns an error.
// If fn returns storer.ErrStop, iteration stops without error.
// Corresponds to git's for_each_note() with each_note_fn callback.
func (iter *NoteIter) ForEach(fn func(*Note) error) error

// Close releases resources.
func (iter *NoteIter) Close()

// Notes returns an iterator over all notes in the tree.
func (nt *NoteTree) Notes() (*NoteIter, error)

// ForEach is a convenience method that calls fn for each note.
func (nt *NoteTree) ForEach(fn func(*Note) error) error
```

**Tests**:

```go
func TestNoteTree_ForEach_AllNotes(t *testing.T) {
    // Iterates over all notes
}

func TestNoteTree_ForEach_StopEarly(t *testing.T) {
    // Stops iteration when fn returns storer.ErrStop
}

func TestNoteTree_ForEach_Empty(t *testing.T) {
    // Handles empty tree gracefully
}

func TestNoteTree_ForEach_Fanout(t *testing.T) {
    // Correctly iterates notes in fanout structure
}

func TestNoteIter_Next(t *testing.T) {
    // Iterator returns notes sequentially
}
```

### Phase 6: Write Notes Tree

> **Git Reference**: Corresponds to [`write_notes_tree()`](https://github.com/git/git/blob/master/notes.c#L1194-L1222) in `notes.c`. The tree writing uses `struct tree_write_stack` ([`notes.c:638-644`](https://github.com/git/git/blob/master/notes.c#L638-L644)) and `write_each_note()` callback ([`notes.c:735-782`](https://github.com/git/git/blob/master/notes.c#L735-L782)).

```go
// Write persists the notes tree to storage and updates the reference.
// Returns the new tree hash, or zero hash if the tree is empty.
// If the tree is not dirty (no changes), this is a no-op.
func (nt *NoteTree) Write() (plumbing.Hash, error)
```

The write operation:
1. Creates blob objects for each note's content
2. Builds a tree structure (using fanout for large numbers of notes)
3. Writes the tree to object storage
4. Updates the notes reference to point to the new tree
5. Clears the dirty flag

**Fanout Strategy**:
> **Git Reference**: See `FANOUT_PATH_SEPARATORS` in [`notes.c:76-77`](https://github.com/git/git/blob/master/notes.c#L76-L77) and the subtree handling in `load_subtree()` ([`notes.c:385-492`](https://github.com/git/git/blob/master/notes.c#L385-L492))

- For small numbers of notes (< 256), use flat structure
- For larger note sets, use 2-character fanout
- This matches git's default behavior

**Tests**:

```go
func TestNoteTree_Write_CreatesBlob(t *testing.T) {
    // Note content is stored as blob object
}

func TestNoteTree_Write_CreatesTree(t *testing.T) {
    // Tree structure is created correctly
}

func TestNoteTree_Write_UpdatesRef(t *testing.T) {
    // Reference is updated to point to new tree
}

func TestNoteTree_Write_NotDirtyNoOp(t *testing.T) {
    // No write occurs if tree is not dirty
}

func TestNoteTree_Write_ClearsDirty(t *testing.T) {
    // Dirty flag is cleared after write
}

func TestNoteTree_Write_Fanout(t *testing.T) {
    // Uses fanout structure for many notes
}
```

### Phase 7: Repository API

> **Git Reference**: The repository-level API corresponds to the CLI commands in [`builtin/notes.c`](https://github.com/git/git/blob/master/builtin/notes.c). The initialization follows [`init_notes()`](https://github.com/git/git/blob/master/notes.c#L1012-L1054) and the default ref resolution follows [`default_notes_ref()`](https://github.com/git/git/blob/master/notes.c#L994-L1009).

**Additions to `repository.go`**:

```go
// DefaultNotesRef is the default notes reference.
const DefaultNotesRef = plumbing.ReferenceName("refs/notes/commits")

// NoteTree returns the notes tree for the given reference.
// If ref is empty, uses DefaultNotesRef.
// Creates an empty NoteTree if the reference doesn't exist.
func (r *Repository) NoteTree(ref plumbing.ReferenceName) (*object.NoteTree, error) {
    if ref == "" {
        ref = DefaultNotesRef
    }
    
    noteRef, err := r.Reference(ref, true)
    if err != nil {
        if err == plumbing.ErrReferenceNotFound {
            // Return empty NoteTree
            return object.NewNoteTree(r.Storer, ref)
        }
        return nil, err
    }
    
    return object.NewNoteTreeFromRef(r.Storer, noteRef)
}

// Note returns the note content for the given object.
// Uses the default notes reference (refs/notes/commits).
// Returns ErrNoteNotFound if no note exists.
func (r *Repository) Note(objectHash plumbing.Hash) (string, error) {
    nt, err := r.NoteTree("")
    if err != nil {
        return "", err
    }
    
    note, err := nt.Get(objectHash)
    if err != nil {
        return "", err
    }
    
    return note.Message, nil
}

// SetNote sets a note for the given object.
// Uses options to configure the note reference and combination strategy.
func (r *Repository) SetNote(objectHash plumbing.Hash, message string, opts *SetNoteOptions) error {
    if opts == nil {
        opts = &SetNoteOptions{}
    }
    
    nt, err := r.NoteTree(opts.Ref)
    if err != nil {
        return err
    }
    
    combine := opts.Combine
    if opts.Force && combine == nil {
        combine = object.CombineNotesOverwrite
    }
    
    if err := nt.Add(objectHash, message, combine); err != nil {
        return err
    }
    
    _, err = nt.Write()
    return err
}

// RemoveNote removes the note for the given object.
func (r *Repository) RemoveNote(objectHash plumbing.Hash, opts *RemoveNoteOptions) error {
    if opts == nil {
        opts = &RemoveNoteOptions{}
    }
    
    nt, err := r.NoteTree(opts.Ref)
    if err != nil {
        return err
    }
    
    if err := nt.Remove(objectHash); err != nil {
        return err
    }
    
    _, err = nt.Write()
    return err
}
```

**Additions to `options.go`**:

```go
// SetNoteOptions describes how a note set operation should be performed.
type SetNoteOptions struct {
    // Ref is the notes reference. If empty, uses DefaultNotesRef.
    Ref plumbing.ReferenceName
    // Force overwrites existing notes without error.
    Force bool
    // Combine specifies how to combine notes when a note already exists.
    // If nil and Force is false, SetNote returns ErrNoteExists.
    // If nil and Force is true, uses CombineNotesOverwrite.
    Combine object.CombineNotesFunc
}

// RemoveNoteOptions describes how a note remove operation should be performed.
type RemoveNoteOptions struct {
    // Ref is the notes reference. If empty, uses DefaultNotesRef.
    Ref plumbing.ReferenceName
}
```

**Tests** (`notes_test.go` at repository root):

```go
func TestRepository_NoteTree_Default(t *testing.T) {
    // Returns NoteTree for default ref
}

func TestRepository_NoteTree_Custom(t *testing.T) {
    // Returns NoteTree for custom ref
}

func TestRepository_NoteTree_Empty(t *testing.T) {
    // Returns empty NoteTree when ref doesn't exist
}

func TestRepository_Note(t *testing.T) {
    // Retrieves note content
}

func TestRepository_Note_NotFound(t *testing.T) {
    // Returns ErrNoteNotFound
}

func TestRepository_SetNote(t *testing.T) {
    // Sets note successfully
}

func TestRepository_SetNote_Force(t *testing.T) {
    // Overwrites with Force option
}

func TestRepository_RemoveNote(t *testing.T) {
    // Removes note successfully
}
```

### Phase 8: Integration Tests

Tests ensuring compatibility with git CLI:

```go
func TestNotes_ReadGitNotes(t *testing.T) {
    // Setup: Create repo with git, add notes via git CLI
    // Test: Read notes with go-git
    // Verify: Content matches
}

func TestNotes_WriteGitCompatible(t *testing.T) {
    // Setup: Create repo with go-git, add notes
    // Test: Read notes with git CLI
    // Verify: Content matches, tree structure is valid
}

func TestNotes_MultipleNamespaces(t *testing.T) {
    // Test multiple note namespaces work independently
}

func TestNotes_LargeFanout(t *testing.T) {
    // Test with 1000+ notes to verify fanout works
}

func TestNotes_RoundTrip(t *testing.T) {
    // Write with go-git, read with git, modify with git, read with go-git
}
```

### Phase 9: Documentation

1. **Update `COMPATIBILITY.md`**:

```markdown
| `notes`    |             | ✅          |       | - [notes](_examples/notes/main.go) |
```

2. **Create `_examples/notes/main.go`**:

```go
package main

import (
    "fmt"
    "os"

    "github.com/go-git/go-git/v6"
    "github.com/go-git/go-git/v6/plumbing"
    "github.com/go-git/go-git/v6/plumbing/object"
)

func main() {
    // Open repository
    r, err := git.PlainOpen(".")
    checkIfError(err)

    // Get HEAD commit
    head, err := r.Head()
    checkIfError(err)

    // Add a note to HEAD
    err = r.SetNote(head.Hash(), "This is a note!", &git.SetNoteOptions{
        Force: true,
    })
    checkIfError(err)
    fmt.Printf("Added note to commit %s\n", head.Hash())

    // Read the note back
    note, err := r.Note(head.Hash())
    checkIfError(err)
    fmt.Printf("Note content: %s\n", note)

    // Use custom namespace
    err = r.SetNote(head.Hash(), `{"reviewed": true}`, &git.SetNoteOptions{
        Ref:   plumbing.NewNoteReferenceName("review"),
        Force: true,
    })
    checkIfError(err)
    fmt.Println("Added review note")

    // Iterate all notes
    nt, err := r.NoteTree("")
    checkIfError(err)
    
    err = nt.ForEach(func(n *object.Note) error {
        fmt.Printf("Note on %s: %s\n", n.Target, n.Message)
        return nil
    })
    checkIfError(err)
}

func checkIfError(err error) {
    if err != nil {
        fmt.Fprintf(os.Stderr, "error: %s\n", err)
        os.Exit(1)
    }
}
```

## File Structure

```
plumbing/object/
├── note.go              # Note, NoteTree, NoteIter types and methods
├── note_test.go         # Unit tests for note functionality

repository.go            # Add NoteTree, Note, SetNote, RemoveNote methods
options.go               # Add SetNoteOptions, RemoveNoteOptions

notes_test.go            # Integration tests at repository level

_examples/notes/
└── main.go              # Usage example

COMPATIBILITY.md         # Update notes row to ✅
```

## Drawbacks

1. **Implementation Complexity**: Git notes use a specialized tree structure with variable fanout that requires careful handling to maintain compatibility.

2. **Memory Usage**: For repositories with many notes, loading the entire notes tree into memory could be expensive. Mitigation: lazy loading.

3. **Concurrent Access**: Notes modifications require careful handling when multiple processes access the same repository. The current design doesn't include locking mechanisms.

4. **Push/Fetch**: This RFC doesn't cover pushing/fetching notes, which requires refspec configuration. Users would need to manually configure `refs/notes/*` refspecs.

## Rationale and Alternatives

### Why This Design?

1. **Follows go-git Patterns**: The NoteTree API mirrors existing patterns (Tree, Commit objects). The Repository methods follow the existing Tag/Branch API style.

2. **Compatible with Git**: By supporting git's fanout structure, notes created by either tool are interoperable.

3. **Flexible Namespaces**: Full support for custom note refs enables use cases like Argo CD's hydrator metadata.

4. **TDD Approach**: The phased implementation with tests first ensures correctness and makes review easier.

### Alternatives Considered

1. **Minimal API (just Get/Set at Repository level)**: Rejected because power users need tree-level access for iteration and batch operations.

2. **Automatic Push/Fetch of Notes**: Rejected as out of scope; can be added later. Notes typically need explicit refspec configuration anyway.

3. **Different Fanout Strategy**: Considered always using fanout, but matching git's behavior (flat for small, fanout for large) is more compatible.

### Impact of Not Doing This

- Users must shell out to git CLI for notes operations (like Argo CD currently does)
- go-git remains incomplete for workflows that depend on notes
- Barrier to adoption for projects that use notes heavily
